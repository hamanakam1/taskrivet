import XCTest
@testable import TaskrivetMac

final class TerminalEnvironmentTests: XCTestCase {
    func testTerminalEnvironmentEncodesLiteralKeysAndValues() throws {
        let variables = TaskrivetTerminalView.defaultEnvironment(
            extra: ["TASKRIVET_DB": "/tmp/synthetic folder/ledger=value.sqlite", "EMPTY": ""],
            inherited: [:], home: "/tmp/synthetic-home")
        let decoded = try decode(variables)
        XCTAssertEqual(decoded["HOME"], "/tmp/synthetic-home")
        XCTAssertEqual(decoded["TERM"], "xterm-256color")
        XCTAssertEqual(decoded["SHELL"], "/bin/zsh")
        XCTAssertEqual(decoded["TASKRIVET_DB"], "/tmp/synthetic folder/ledger=value.sqlite")
        XCTAssertEqual(decoded["EMPTY"], "")
        XCTAssertTrue(try XCTUnwrap(decoded["PATH"]).contains("/usr/bin"))
        XCTAssertTrue(variables.contains("TASKRIVET_DB=/tmp/synthetic folder/ledger=value.sqlite"))
    }

    func testTerminalPreservesConfiguredSourceButOmitsRunIdentityAndUnrelatedValues() throws {
        let configured = [
            "TASKRIVET_PYTHON": "/tmp/synthetic/python",
            "TASKRIVET_DB": "/tmp/synthetic/ledger.sqlite",
            "TASKRIVET_CONFIG": "/tmp/synthetic/config.json",
            "TASKRIVET_SESSION_DIR": "/tmp/synthetic/sessions",
            "PYTHONPATH": "/tmp/synthetic/source",
        ]
        let inherited = configured.merging([
            "TASKRIVET_SESSION": "synthetic-run-session",
            "TASKRIVET_TASK": "synthetic-task",
            "TASKRIVET_CONTEXT": "/tmp/synthetic/context",
            "UNRELATED_VALUE": "synthetic-value",
        ]) { _, value in value }
        let decoded = try decode(TaskrivetTerminalView.defaultEnvironment(
            extra: [:], inherited: inherited, home: "/tmp/synthetic-home"))
        for (key, value) in configured { XCTAssertEqual(decoded[key], value) }
        for key in ["TASKRIVET_SESSION", "TASKRIVET_TASK", "TASKRIVET_CONTEXT", "UNRELATED_VALUE"] {
            XCTAssertNil(decoded[key])
        }
    }

    private func decode(_ variables: [String]) throws -> [String: String] {
        var result: [String: String] = [:]
        for variable in variables {
            let separator = try XCTUnwrap(variable.firstIndex(of: "="))
            let key = String(variable[..<separator])
            XCTAssertNil(result[key], "Duplicate environment key")
            result[key] = String(variable[variable.index(after: separator)...])
        }
        return result
    }
}
