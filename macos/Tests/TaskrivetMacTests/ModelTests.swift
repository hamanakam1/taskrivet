import XCTest
@testable import TaskrivetMac

/// All fixtures are synthetic; none of this data comes from a real ledger.
final class ModelTests: XCTestCase {

    func testLinksEnvelopeFullRow() throws {
        let json = """
        {
          "schema": 2,
          "generated_at": 1700000000.5,
          "links": [
            {
              "ticket_key": "T-7",
              "task_id": "ticket-t-7",
              "task_status": "running",
              "origin": "http://127.0.0.1:8080",
              "title": "Synthetic demo ticket",
              "revision": "abc123",
              "imported": 1699999000.0,
              "refreshed": 1700000000.0,
              "holds": ["No-auto execution hold", "Readiness: UNKNOWN"],
              "acknowledged": ["No-auto execution hold"],
              "session": {"id": "s-1", "owner": "demo", "status": "active",
                          "lease_remaining_seconds": 42, "reported_tokens": 10},
              "checkpoint": {"summary": "did a thing", "next_step": "do more", "created": 1699999900.0},
              "failures": 2,
              "last_failure": {"category": "timeout", "summary": "synthetic timeout", "created": 1699999950.0},
              "handback": {"id": "hb1", "status": "pending", "attempts": 1,
                           "last_error": null, "updated": 1700000000.0, "delivered": null},
              "agent": {"tool": "demo-tool", "terminal": "t-1", "session": "s-1",
                        "launched": 1699999900.0, "run_dir": "/tmp/synthetic-run"}
            }
          ],
          "provenance": "Ledger records only."
        }
        """.data(using: .utf8)!
        let envelope = try TaskrivetJSON.decode(LinksEnvelope.self, from: json)
        XCTAssertEqual(envelope.schema, 2)
        let row = try XCTUnwrap(envelope.links.first)
        XCTAssertEqual(row.ticketKey, "T-7")
        XCTAssertEqual(row.origin, "http://127.0.0.1:8080")
        XCTAssertEqual(row.unacknowledgedHolds, ["Readiness: UNKNOWN"])
        XCTAssertEqual(row.session?.leaseRemainingSeconds, 42)
        XCTAssertEqual(row.checkpoint?.nextStep, "do more")
        XCTAssertEqual(row.handback?.status, "pending")
        XCTAssertEqual(row.agent?.runDir, "/tmp/synthetic-run")
    }

    func testLinksEnvelopeMinimalRow() throws {
        let json = """
        {
          "schema": 2, "generated_at": 1700000000.0,
          "links": [
            {"ticket_key": "T-9", "task_id": "ticket-t-9", "task_status": "ready",
             "title": null, "revision": null, "imported": null, "refreshed": null,
             "holds": [], "acknowledged": null, "session": null, "checkpoint": null,
             "failures": 0, "last_failure": null, "handback": null, "agent": null}
          ]
        }
        """.data(using: .utf8)!
        let envelope = try TaskrivetJSON.decode(LinksEnvelope.self, from: json)
        let row = try XCTUnwrap(envelope.links.first)
        XCTAssertNil(row.session)
        XCTAssertNil(row.origin)
        XCTAssertNil(row.handback)
        XCTAssertEqual(row.unacknowledgedHolds, [])
        XCTAssertNil(envelope.provenance)
    }

    func testStatusScopeIsStringDetailScopeIsArray() throws {
        let statusJson = """
        {"tasks": [{"id": "t-1", "objective": "synthetic", "acceptance": null,
                    "kind": "code", "scope": "[\\"synthetic/key\\"]",
                    "status": "ready", "token_budget": 100, "created": 1700000000.0}]}
        """.data(using: .utf8)!
        let status = try TaskrivetJSON.decode(StatusEnvelope.self, from: statusJson)
        XCTAssertEqual(status.tasks.first?.scopeKeys, ["synthetic/key"])

        let detailJson = """
        {"task": {"id": "t-1", "objective": "synthetic", "acceptance": null, "kind": "code",
                  "scope": ["synthetic/key"], "status": "ready", "token_budget": 100,
                  "created": 1700000000.0, "reported_tokens": 0, "remaining_tokens": 100},
         "session": null, "sessions": [], "checkpoints": [], "context": [], "failures": [],
         "events": [], "claims": [], "pack": {"bytes": 12, "items": 1, "omitted": [], "error": null}}
        """.data(using: .utf8)!
        let detail = try TaskrivetJSON.decode(DetailEnvelope.self, from: detailJson)
        XCTAssertEqual(detail.task.scope, ["synthetic/key"])
        XCTAssertEqual(detail.pack?.items, 1)
    }

    func testSessionsEnvelope() throws {
        let json = """
        {"service": "running", "implementation": "demo", "directory": "/tmp/synthetic",
         "terminals": [{"id": "t-1", "title": null, "kind": "shell", "ref": null,
                        "task": null, "session": null, "state": "running",
                        "exit_code": null, "pid": 1234, "cwd": "/tmp",
                        "command": "zsh", "output_bytes": 42, "last_line": null}]}
        """.data(using: .utf8)!
        let envelope = try TaskrivetJSON.decode(SessionsEnvelope.self, from: json)
        XCTAssertEqual(envelope.service, "running")
        XCTAssertEqual(envelope.terminals?.first?.pid, 1234)
    }

    func testDoctorEnvelope() throws {
        let json = """
        {"status": "warn", "checks": [{"check": "python", "status": "ok", "detail": "synthetic"},
                                       {"check": "ledger", "status": "warn", "detail": null}]}
        """.data(using: .utf8)!
        let doctor = try TaskrivetJSON.decode(DoctorEnvelope.self, from: json)
        XCTAssertEqual(doctor.status, "warn")
        XCTAssertEqual(doctor.checks.map(\.check), ["python", "ledger"])
    }

    func testJSONValueRendering() throws {
        let json = """
        {"note": "synthetic", "n": 3.0, "ok": true, "list": [1.0, "x"], "nothing": null}
        """.data(using: .utf8)!
        let value = try TaskrivetJSON.decode([String: JSONValue].self, from: json)
        XCTAssertEqual(value["note"], .string("synthetic"))
        XCTAssertEqual(value["n"]?.rendered, "3")
        XCTAssertEqual(value["list"]?.rendered, #"[1, x]"#)
        XCTAssertEqual(value["nothing"], .null)
    }

    func testDiscoveryOrder() {
        let candidates = PythonDiscovery.candidates(
            env: ["TASKRIVET_PYTHON": "/synthetic/python"],
            fileExists: { _ in true },
            pathLookup: { "/synthetic/path-python" })
        XCTAssertEqual(candidates.first, "/synthetic/python")
        XCTAssertEqual(candidates.last, "/synthetic/path-python")
        XCTAssertTrue(candidates.contains("/opt/homebrew/bin/python3"))
    }

    func testDiscoverySkipsMissing() {
        let candidates = PythonDiscovery.candidates(
            env: [:],
            fileExists: { $0 == "/usr/bin/python3" },
            pathLookup: { nil })
        XCTAssertEqual(candidates, ["/usr/bin/python3"])
    }

    func testBridgeErrorMessages() {
        let error = CoreBridgeError.noPython(tried: ["/a", "/b"])
        XCTAssertTrue(error.message.contains("/a"))
        XCTAssertTrue(error.message.contains("TASKRIVET_PYTHON"))
        let exit = CoreBridgeError.nonZeroExit(code: 2, stderr: "line1\nline2")
        XCTAssertTrue(exit.message.contains("2"))
    }
}
