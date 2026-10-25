import SwiftUI
import SwiftTerm

/// A SwiftTerm local-process terminal inside SwiftUI. The PTY runs the exact
/// argument vector it is given; interactive CLIs (an agent console, an
/// `attach` follow) keep their own prompts and detach keys.
struct TaskrivetTerminalView: NSViewRepresentable {
    let executable: String
    let args: [String]
    let workingDirectory: String?
    /// Extra environment on top of a curated default set. GUI launches get a
    /// sparse PATH, so a sane default is provided and the login shell still
    /// sources the user's own profile on top.
    var extraEnvironment: [String: String] = [:]
    var onExit: (Int32) -> Void = { _ in }
    var onTitle: (String) -> Void = { _ in }

    static func defaultEnvironment(extra: [String: String]) -> [String] {
        let home = NSHomeDirectory()
        var env: [String: String] = [
            "HOME": home,
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "TERM_PROGRAM": "Taskrivet",
            "SHELL": "/bin/zsh",
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ]
        for (key, value) in ProcessInfo.processInfo.environment
        where ["TASKRIVET_PYTHON", "TASKRIVET_DB", "SSH_AUTH_SOCK", "COLORTERM"].contains(key) {
            env[key] = value
        }
        for (key, value) in extra { env[key] = value }
        // SwiftTerm expects "KEY=value" strings.
        return env.map { "\($0)=\(1)" }
    }

    func makeNSView(context: Context) -> LocalProcessTerminalView {
        let view = LocalProcessTerminalView(frame: .zero)
        view.processDelegate = context.coordinator
        let env = TaskrivetTerminalView.defaultEnvironment(extra: extraEnvironment)
        // SwiftTerm 1.5.0 inherits the app process's working directory for
        // the spawned PTY, so set it for the duration of the spawn only.
        // This is main-thread, synchronous, and restored immediately after.
        let previous = FileManager.default.currentDirectoryPath
        if let workingDirectory {
            FileManager.default.changeCurrentDirectoryPath(workingDirectory)
        }
        view.startProcess(executable: executable, args: args, environment: env)
        FileManager.default.changeCurrentDirectoryPath(previous)
        return view
    }

    func updateNSView(_ nsView: LocalProcessTerminalView, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onExit: onExit, onTitle: onTitle)
    }

    @MainActor
    final class Coordinator: NSObject, LocalProcessTerminalViewDelegate {
        let onExit: (Int32) -> Void
        let onTitle: (String) -> Void

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
