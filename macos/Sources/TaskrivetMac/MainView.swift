import SwiftUI
import AppKit

/// Window layout: sidebar (ticket loop, tasks, session terminals),
/// the inspector for the selected task, and the terminal tab strip.
struct MainView: View {
    @ObservedObject var state: AppState
    @State private var selection: String?
    @State private var showDoctor = false

    var body: some View {
        NavigationSplitView {
            SidebarView(state: state, selection: $selection)
                .navigationTitle("Taskrivet")
        } detail: {
            HSplitView {
                InspectorView(state: state)
                    .frame(minWidth: 320, idealWidth: 420)
                TerminalAreaView(state: state)
                    .frame(minWidth: 420)
            }
        }
        .toolbar { toolbar }
        .onChange(of: selection) { _, newValue in state.select(task: newValue) }
        .onAppear {
            if state.bridge == nil && state.bridgeError == nil { state.connect() }
            state.refresh()
        }
        .task {
            // Read views stay current while this workspace is open. This is
            // observation only; the timer never launches or claims work.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                guard !Task.isCancelled else { return }
                state.refreshRouting()
                state.refresh()
            }
        }
        .sheet(isPresented: $showDoctor) { DoctorSheet(state: state) }
    }

    @ToolbarContentBuilder
    var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                pickFolderAndOpenShell()
            } label: {
                Label("New terminal", systemImage: "plus.rectangle.on.rectangle")
            }
            .help("Open a login shell in a folder you pick. Nothing runs until you pick the folder.")

            Button {
                showDoctor = true
            } label: {
                Label("Doctor", systemImage: "stethoscope")
            }

            Button {
                state.connect()
                state.refresh()
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .keyboardShortcut("r", modifiers: .command)
            .disabled(state.refreshing)
        }
    }

    private func pickFolderAndOpenShell() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Open shell here"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        state.openShell(in: url.path)
    }
}

// MARK: - Terminal area

struct TerminalAreaView: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(spacing: 0) {
            if !state.tabs.isEmpty {
                tabStrip
                Divider()
            }
            ZStack {
                ForEach(state.tabs) { tab in
                    terminalView(for: tab)
                        .opacity(tab.id == state.activeTab ? 1 : 0)
                        .allowsHitTesting(tab.id == state.activeTab)
                        .accessibilityHidden(tab.id != state.activeTab)
                }
                if state.tabs.isEmpty {
                    VStack(spacing: 10) {
                        Image(systemName: "apple.terminal")
                            .font(.largeTitle)
                            .foregroundStyle(.secondary)
                        Text("No terminal open")
                            .foregroundStyle(.secondary)
                        Text("Use + to open a login shell, or Attach next to a running session terminal.")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: .textBackgroundColor))
        }
    }

    var tabStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 4) {
                ForEach(state.tabs) { tab in
                    TabCellView(tab: tab, isActive: tab.id == state.activeTab) {
                        state.activeTab = tab.id
                    } onClose: {
                        state.close(tab: tab.id)
                    }
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
        }
    }

    @ViewBuilder
    func terminalView(for tab: TerminalTab) -> some View {
        switch tab.content {
        case .shell(let directory):
            TaskrivetTerminalView(
                executable: "/bin/zsh",
                args: ["-l"],
                workingDirectory: directory,
                isActive: tab.id == state.activeTab,
                onExit: { code in state.noteExit(tab: tab.id, code: code) },
                onTitle: { title in
                    guard let index = state.tabs.firstIndex(where: { $0.id == tab.id }) else { return }
                    state.tabs[index].title = title.isEmpty ? tab.title : title
                }
            )
        case .attach(let terminalId, _):
            if let bridge = state.bridge {
                let command = bridge.attachCommand(terminal: terminalId)
                TaskrivetTerminalView(
                    executable: command.executable,
                    args: command.args,
                    workingDirectory: nil,
                    isActive: tab.id == state.activeTab,
                    onExit: { code in state.noteExit(tab: tab.id, code: code) }
                )
            } else {
                ContentUnavailableView("CLI bridge unavailable",
                                       systemImage: "exclamationmark.triangle",
                                       description: Text(state.bridgeError ?? "Not connected."))
            }
        }
    }
}

/// One tab in the terminal strip. Kept as its own view so the strip's body
/// stays small enough for the type checker.
struct TabCellView: View {
    let tab: TerminalTab
    let isActive: Bool
    let onSelect: () -> Void
    let onClose: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            if let code = tab.exitedWith {
                Image(systemName: code == 0 ? "checkmark.circle" : "xmark.circle")
                    .foregroundStyle(code == 0 ? Color.secondary : Color.red)
            }
            Text(tab.title).lineLimit(1)
            Button(action: onClose) {
                Image(systemName: "xmark")
            }
            .buttonStyle(.borderless)
        }
        .font(.caption)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(isActive ? Color.accentColor.opacity(0.2) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .onTapGesture(perform: onSelect)
    }
}

// MARK: - Doctor sheet

struct DoctorSheet: View {
    @ObservedObject var state: AppState
    @State private var result: DoctorEnvelope?
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Doctor").font(.title2.bold())
                Spacer()
                Button("Close") { dismiss() }
            }
            if let result {
                Text("Overall: \(result.status)")
                    .font(.headline)
                    .foregroundStyle(result.status == "ok" ? Color.green : Color.orange)
                List(result.checks) { check in
                    HStack(alignment: .top) {
                        Image(systemName: check.status == "ok" ? "checkmark.circle.fill"
                              : check.status == "warn" ? "exclamationmark.triangle.fill" : "xmark.circle.fill")
                            .foregroundStyle(check.status == "ok" ? Color.green
                                             : check.status == "warn" ? Color.orange : Color.red)
                        VStack(alignment: .leading) {
                            Text(check.check).font(.callout.bold())
                            if let detail = check.detail {
                                Text(detail).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            } else if let error {
                Text(error).foregroundStyle(.red)
            } else {
                ProgressView("Running checks…")
            }
        }
        .padding()
        .frame(minWidth: 520, minHeight: 380)
        .onAppear(perform: run)
    }

    private func run() {
        guard let bridge = state.bridge else {
            error = state.bridgeError ?? "CLI bridge unavailable."
            return
        }
        Task.detached { [bridge] in
            let outcome = bridge.doctor()
            await MainActor.run {
                switch outcome {
                case .success(let value): result = value
                case .failure(let failure): error = failure.message
                }
            }
        }
    }
}
