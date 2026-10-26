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
        Task.detached { [bridge] in
            let links = bridge.links()
            let status = bridge.status()
            let sessions = bridge.sessions()
            let launchers = bridge.launchers()
            var detail: Result<DetailEnvelope, CoreBridgeError>?
            if let selected {
                detail = bridge.detail(task: selected)
            }
            await MainActor.run { [weak self] in
                guard let self else { return }
                if case .success(let value) = links {
                    self.links = value.links
                    self.provenance = value.provenance
                }
                if case .success(let value) = status { self.tasks = value.tasks }
                if case .success(let value) = sessions {
                    self.terminals = value.terminals ?? []
                    self.sessionService = value.service
                }
                if case .success(let value) = launchers { self.launchers = value.launchers }
                if let detail {
                    switch detail {
                    case .success(let value):
                        self.detail = value
                        self.detailError = nil
                    case .failure(let error):
                        self.detailError = error.message
                    }
                }
                self.lastRefresh = Date()
                self.refreshing = false
            }
        }
    }

    func select(task id: String?) {
        selectedTaskId = id
        guard let id, let bridge else {
            detail = nil
            return
        }
        Task.detached { [bridge] in
            let result = bridge.detail(task: id)
            await MainActor.run { [weak self] in
                guard let self, self.selectedTaskId == id else { return }
                switch result {
                case .success(let value):
                    self.detail = value
                    self.detailError = nil
                case .failure(let error):
                    self.detail = nil
                    self.detailError = error.message
                }
            }
        }
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
