import Foundation

/// Locates a Python interpreter that can import the `taskrivet` package.
///
/// Order: TASKRIVET_PYTHON environment override, then well-known interpreter
/// locations, then a PATH lookup. A candidate qualifies only if
/// `<python> -c "import taskrivet"` exits zero, so the app never shells out
/// to an interpreter that would fail every call.
struct PythonDiscovery {
    /// Well-known interpreter locations, tried in order after the override.
    /// These are stock macOS/Homebrew paths, not machine-specific config.
    static let standardCandidates = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ]

    /// All candidates in probe order: env override, standard paths, PATH hit.
    static func candidates(env: [String: String] = ProcessInfo.processInfo.environment,
                           fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) },
                           pathLookup: () -> String? = { PythonDiscovery.pathPython() }) -> [String] {
        var result: [String] = []
        if let override = env["TASKRIVET_PYTHON"], !override.isEmpty {
            result.append(override)
        }
        for path in standardCandidates where fileExists(path) {
            result.append(path)
        }
        if let found = pathLookup(), !result.contains(found) {
            result.append(found)
        }
        return result
    }

    private static func pathPython() -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        process.arguments = ["python3"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        guard let _ = try? process.run() else { return nil }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let path = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return path.isEmpty ? nil : path
    }
}

enum CoreBridgeError: Error, Equatable {
    case noPython(tried: [String])
    case launchFailed(String)
    case timedOut
    case nonZeroExit(code: Int32, stderr: String)
    case notJSON(String)

    var message: String {
        switch self {
        case .noPython(let tried):
            return "No Python interpreter with the taskrivet package was found. " +
                   "Tried: \(tried.joined(separator: ", ")). " +
                   "Set TASKRIVET_PYTHON to a Python 3.11+ with taskrivet installed."
        case .launchFailed(let detail): return "Could not launch the CLI: \(detail)"
        case .timedOut: return "The CLI did not answer in time."
        case .nonZeroExit(let code, let stderr):
            let tail = stderr.split(separator: "\\n").suffix(4).joined(separator: " ")
            return "CLI exited \(code). \(tail)"
        case .notJSON(let head): return "The CLI output was not JSON: \(head.prefix(120))"
        }
    }
}

/// Runs the taskrivet CLI with an argument vector (never a shell) and decodes
/// its JSON stdout. Every call is a fresh process; the app keeps no Python
/// resident and holds no ledger handle.
final class CoreBridge: @unchecked Sendable {
    let python: String
    private let bundledCore: String?

    init(python: String, bundledCore: String? = CoreBridge.bundledCorePath()) {
        self.python = python
        self.bundledCore = bundledCore
    }

    private static func bundledCorePath() -> String? {
        guard let path = Bundle.main.resourceURL?.appendingPathComponent("core").path,
              FileManager.default.fileExists(atPath: path) else { return nil }
        return path
    }

    /// Probe the candidate list once and return the first interpreter that
    /// imports taskrivet successfully.
    static func connect(candidates: [String] = PythonDiscovery.candidates()) -> Result<CoreBridge, CoreBridgeError> {
        for candidate in candidates {
            if probe(python: candidate, bundledCore: bundledCorePath()) {
                return .success(CoreBridge(python: candidate))
            }
        }
        return .failure(.noPython(tried: candidates))
    }

    static func probe(python: String, bundledCore: String? = bundledCorePath()) -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-c", "import taskrivet"]
        process.environment = environment(with: bundledCore)
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            return false
        }
        // A hung interpreter must not wedge the UI; give probes five seconds.
        let deadline = Date().addingTimeInterval(5)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
        if process.isRunning {
            process.terminate()
            return false
        }
        return process.terminationStatus == 0
    }

    private static func environment(with bundledCore: String?) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        if let bundledCore, !bundledCore.isEmpty {
            let prior = env["PYTHONPATH"]
            env["PYTHONPATH"] = prior.map { bundledCore + ":" + $0 } ?? bundledCore
        }
        return env
    }

    /// Synchronous JSON call with a timeout. Callers invoke from a background
    /// queue; the result is the parsed stdout or a typed error.
    func call<T: Decodable>(_ type: T.Type, _ args: [String], timeout: TimeInterval = 30) -> Result<T, CoreBridgeError> {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", "taskrivet", "--format", "json"] + args
        process.environment = Self.environment(with: bundledCore)
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        do {
            try process.run()
        } catch {
            return .failure(.launchFailed(error.localizedDescription))
        }

        // Drain both pipes on background threads so a chatty child can never
        // fill a pipe buffer and deadlock against waitUntilExit.
        var outData = Data()
        var errData = Data()
        let outThread = Thread {
            outData = stdout.fileHandleForReading.readDataToEndOfFile()
        }
        let errThread = Thread {
            errData = stderr.fileHandleForReading.readDataToEndOfFile()
        }
        outThread.start()
        errThread.start()

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
        if process.isRunning {
            process.terminate()
            return .failure(.timedOut)
        }
        while outThread.isExecuting || errThread.isExecuting {
            Thread.sleep(forTimeInterval: 0.01)
        }

        guard process.terminationStatus == 0 else {
            return .failure(.nonZeroExit(code: process.terminationStatus,
                                         stderr: String(decoding: errData, as: UTF8.self)))
        }
        do {
            return .success(try TaskrivetJSON.decode(type, from: outData))
        } catch {
            return .failure(.notJSON(String(decoding: outData, as: UTF8.self)))
        }
    }

    // Convenience accessors for the envelopes the app renders.

    func status() -> Result<StatusEnvelope, CoreBridgeError> { call(StatusEnvelope.self, ["status"]) }
    func links() -> Result<LinksEnvelope, CoreBridgeError> { call(LinksEnvelope.self, ["links"]) }
    func sessions() -> Result<SessionsEnvelope, CoreBridgeError> { call(SessionsEnvelope.self, ["sessions"]) }
    func detail(task: String) -> Result<DetailEnvelope, CoreBridgeError> {
        call(DetailEnvelope.self, ["detail", "--task", task])
    }
    func launchers() -> Result<LaunchersEnvelope, CoreBridgeError> { call(LaunchersEnvelope.self, ["launchers"]) }
    func doctor() -> Result<DoctorEnvelope, CoreBridgeError> { call(DoctorEnvelope.self, ["doctor"], timeout: 90) }

    /// Argument vector for an interactive `attach` in a terminal tab.
    func attachCommand(terminal id: String) -> (executable: String, args: [String]) {
        (python, ["-m", "taskrivet", "attach", id])
    }
}
