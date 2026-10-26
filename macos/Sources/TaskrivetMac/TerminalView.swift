import SwiftUI
import SwiftTerm

/// A SwiftTerm local-process terminal inside SwiftUI. The PTY runs the exact
/// argument vector it is given; interactive CLIs (an agent console, an
/// `attach` follow) keep their own prompts and detach keys.
struct TaskrivetTerminalView: NSViewRepresentable {
    let executable: String
    let args: [String]
    let workingDirectory: String?
    var isActive = true
    /// Extra environment on top of a curated default set. GUI launches get a
    /// sparse PATH, so a sane default is provided and the login shell still
    /// sources the user's own profile on top.
    var extraEnvironment: [String: String] = [:]
    var onExit: (Int32) -> Void = { _ in }
    var onTitle: (String) -> Void = { _ in }

    static func defaultEnvironment(extra: [String: String],
                                   inherited: [String: String] = ProcessInfo.processInfo.environment,
                                   home: String = NSHomeDirectory()) -> [String] {
        var env: [String: String] = [
            "HOME": home,
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "TERM_PROGRAM": "Taskrivet",
            "SHELL": "/bin/zsh",
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ]
        for (key, value) in inherited
        where ["TASKRIVET_PYTHON", "TASKRIVET_DB", "TASKRIVET_CONFIG", "TASKRIVET_SESSION_DIR",
               "PYTHONPATH", "SSH_AUTH_SOCK", "COLORTERM"].contains(key) {
            env[key] = value
        }
        for (key, value) in extra { env[key] = value }
        // SwiftTerm expects "KEY=value" strings.
        return env.map { key, value in "\(key)=\(value)" }
    }

    func makeNSView(context: Context) -> LocalProcessTerminalView {
        let view = LocalProcessTerminalView(frame: .zero)
        view.processDelegate = context.coordinator
        context.coordinator.isActive = isActive
        let env = TaskrivetTerminalView.defaultEnvironment(extra: extraEnvironment)
        // Set only the child's directory; background CLI reads must retain
        // the app's directory while another terminal starts.
        view.startProcess(executable: executable, args: args, environment: env,
                          currentDirectory: workingDirectory)
        return view
    }

    func updateNSView(_ nsView: LocalProcessTerminalView, context: Context) {
        guard context.coordinator.isActive != isActive else { return }
        context.coordinator.isActive = isActive
        if isActive {
            nsView.window?.makeFirstResponder(nsView)
        } else if nsView.window?.firstResponder === nsView {
            nsView.window?.makeFirstResponder(nil)
        }
    }

    static func dismantleNSView(_ nsView: LocalProcessTerminalView, coordinator: Coordinator) {
        // Removing a tab closes its local shell or attach client. Merely
        // switching tabs leaves every open view and process mounted.
        nsView.terminate()
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(onExit: onExit, onTitle: onTitle)
    }

    @MainActor
    final class Coordinator: NSObject, LocalProcessTerminalViewDelegate {
        let onExit: (Int32) -> Void
        let onTitle: (String) -> Void
        var isActive = false

        init(onExit: @escaping (Int32) -> Void, onTitle: @escaping (String) -> Void) {
            self.onExit = onExit
            self.onTitle = onTitle
        }

        func sizeChanged(source: LocalProcessTerminalView, newCols: Int, newRows: Int) {}

        func setTerminalTitle(source: LocalProcessTerminalView, title: String) {
            onTitle(title)
        }

        func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}

        func processTerminated(source: TerminalView, exitCode: Int32?) {
            onExit(exitCode ?? -1)
        }
    }
}
