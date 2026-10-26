import Foundation
import SwiftUI

/// One open terminal tab: a shell, or a live attach to a session-service
/// terminal. The PTY is owned by the tab's view; this is the catalog entry.
struct TerminalTab: Identifiable, Equatable {
    enum Content: Equatable {
        case shell(workingDirectory: String)
        case attach(terminalId: String, task: String?)
    }

    let id: UUID
    var title: String
    let content: Content
    var exitedWith: Int32?

    static func == (lhs: TerminalTab, rhs: TerminalTab) -> Bool {
        lhs.id == rhs.id && lhs.title == rhs.title && lhs.content == rhs.content
            && lhs.exitedWith == rhs.exitedWith
    }
}

/// Request generations also distinguish a selection that goes A → B → A.
struct DetailRead: Equatable {
    let task: String
    let generation: UInt64
}

struct RoutingRead: Equatable {
    let task: String
    let ticket: String
    let origin: String
    let selectionGeneration: UInt64
}

/// Observable store for the whole window. All ledger reads go through the
/// CLI bridge; nothing here writes to the ledger. Operator actions that do
/// write (work, handback, checkpoint) stay in the terminal tabs where the
/// operator drives the CLI interactively and sees every prompt.
@MainActor
final class AppState: ObservableObject {
    @Published var bridge: CoreBridge?
    @Published var bridgeError: String?

    @Published var links: [LinkRow] = []
    @Published var tasks: [TaskRow] = []
    @Published var terminals: [TerminalRecord] = []
    @Published var sessionService: String = "unknown"
    @Published var launchers: [Launcher] = []
    @Published var provenance: String?

    @Published var selectedTaskId: String?
    @Published var detail: DetailEnvelope?
    @Published var detailError: String?

    @Published var routing: RoutingEnvelope?
    @Published var routingError: String?
    @Published var routingRefreshing = false
    private var detailGeneration: UInt64 = 0
    private var selectionGeneration: UInt64 = 0
    private var routingRead: RoutingRead?

    var selectedLink: LinkRow? { links.first { $0.taskId == selectedTaskId } }

    @Published var tabs: [TerminalTab] = []
    @Published var activeTab: UUID?
    @Published var lastRefresh: Date?
    @Published var refreshing = false

    /// Reconnect to the CLI bridge (python discovery probe).
    func connect() {
        switch CoreBridge.connect() {
        case .success(let bridge):
            self.bridge = bridge
            self.bridgeError = nil
        case .failure(let error):
            self.bridge = nil
            self.bridgeError = error.message
        }
    }

    /// Refresh all read views. Failures leave the previous data in place and
    /// surface as the bridge error line; views never fabricate zeros.
    func refresh() {
        guard let bridge, !refreshing else { return }
        refreshing = true
        let selected = selectedTaskId
        let detailRead = selected.map { beginDetailRead(task: $0) }
        refreshRouting()
        Task.detached { [bridge] in
            let links = bridge.links()
            let status = bridge.status()
            let sessions = bridge.sessions()
            let launchers = bridge.launchers()
            let detail = selected.map { bridge.detail(task: $0) }
            await MainActor.run { [weak self] in
                guard let self else { return }
                if case .success(let value) = links {
                    let previousLink = self.selectedLink
                    self.links = value.links
                    self.provenance = value.provenance
                    if previousLink?.ticketKey != self.selectedLink?.ticketKey
                        || previousLink?.origin != self.selectedLink?.origin {
                        self.routing = nil
                        self.routingError = nil
                    }
                }
                if case .success(let value) = status { self.tasks = value.tasks }
                if case .success(let value) = sessions {
                    self.terminals = value.terminals ?? []
                    self.sessionService = value.service
                }
                if case .success(let value) = launchers { self.launchers = value.launchers }
                if let detail, let detailRead {
                    self.applyDetail(detail, request: detailRead)
                }
                self.lastRefresh = Date()
                self.refreshing = false
                // A newly imported link may have arrived in this refresh.
                if self.routing == nil && self.routingError == nil { self.refreshRouting() }
            }
        }
    }

    func select(task id: String?) {
        selectedTaskId = id
        selectionGeneration &+= 1
        detailGeneration &+= 1
        detail = nil
        detailError = nil
        routing = nil
        routingError = nil
        guard let id, let bridge else {
            return
        }
        let request = beginDetailRead(task: id)
        refreshRouting()
        Task.detached { [bridge] in
            let result = bridge.detail(task: id)
            await MainActor.run { [weak self] in
                self?.applyDetail(result, request: request)
            }
        }
    }

    func beginDetailRead(task: String) -> DetailRead {
        detailGeneration &+= 1
        return DetailRead(task: task, generation: detailGeneration)
    }

    func applyDetail(_ result: Result<DetailEnvelope, CoreBridgeError>, request: DetailRead) {
        guard selectedTaskId == request.task, detailGeneration == request.generation else { return }
        switch result {
        case .success(let value):
            guard value.task.id == request.task else {
                detail = nil
                detailError = "The detail response belongs to a different task."
                return
            }
            detail = value
            detailError = nil
        case .failure(let error):
            detail = nil
            detailError = error.message
        }
    }

    /// Only one route process may run at once. A changed selection queues its
    /// read behind the existing process; that process's result is discarded.
    func refreshRouting() {
        guard let bridge, let request = beginRoutingRead() else { return }
        Task.detached { [bridge] in
            let result = bridge.ticketRoute(key: request.ticket, origin: request.origin)
            await MainActor.run { [weak self] in
                guard let self else { return }
                let superseded = self.applyRouting(result, request: request)
                if superseded { self.refreshRouting() }
            }
        }
    }

    func beginRoutingRead() -> RoutingRead? {
        guard !routingRefreshing, let selectedTaskId, let link = selectedLink else { return nil }
        guard let origin = link.origin, !origin.isEmpty else {
            routing = nil
            routingError = "This imported task has no source origin. Update the CLI or reimport from the original ticket service before reading routes."
            return nil
        }
        let request = RoutingRead(task: selectedTaskId, ticket: link.ticketKey, origin: origin,
                                  selectionGeneration: selectionGeneration)
        routingRead = request
        routingRefreshing = true
        routingError = nil
        return request
    }

    /// Returns true when the current selection needs a replacement read.
    @discardableResult
    func applyRouting(_ result: Result<RoutingEnvelope, CoreBridgeError>, request: RoutingRead) -> Bool {
        guard routingRead == request else { return false }
        routingRead = nil
        routingRefreshing = false
        guard selectedTaskId == request.task, selectedLink?.ticketKey == request.ticket,
              selectedLink?.origin == request.origin,
              selectionGeneration == request.selectionGeneration else { return true }
        switch result {
        case .success(let value):
            if let error = value.displayError(for: request.ticket, origin: request.origin) {
                routing = nil
                routingError = error
            } else {
                routing = value
                routingError = nil
            }
        case .failure(let error):
            routing = nil
            routingError = error.message
        }
        return false
    }

    // MARK: - Terminal tabs

    @discardableResult
    func openShell(in directory: String) -> TerminalTab {
        let tab = TerminalTab(id: UUID(), title: URL(fileURLWithPath: directory).lastPathComponent,
                              content: .shell(workingDirectory: directory))
        tabs.append(tab)
        activeTab = tab.id
        return tab
    }

    @discardableResult
    func attach(to terminal: TerminalRecord) -> TerminalTab {
        if let existing = tabs.first(where: {
            if case .attach(let id, _) = $0.content { return id == terminal.id }
            return false
        }) {
            activeTab = existing.id
            return existing
        }
        let tab = TerminalTab(id: UUID(),
                              title: terminal.title ?? terminal.command ?? String(terminal.id.prefix(8)),
                              content: .attach(terminalId: terminal.id, task: terminal.task))
        tabs.append(tab)
        activeTab = tab.id
        return tab
    }

    func close(tab id: UUID) {
        tabs.removeAll { $0.id == id }
        if activeTab == id { activeTab = tabs.last?.id }
    }

    func noteExit(tab id: UUID, code: Int32) {
        guard let index = tabs.firstIndex(where: { $0.id == id }) else { return }
        tabs[index].exitedWith = code
    }
}
