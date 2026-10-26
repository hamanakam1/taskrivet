import XCTest
@testable import TaskrivetMac

final class RoutingTests: XCTestCase {
    private func route(key: String = "DEMO-7", status: String = "recommended") throws -> RoutingEnvelope {
        let data = """
        {
          "schema": "taskrivet.route.v1", "ticket": {"key": "\(key)", "revision": "synthetic-revision"},
          "status": "\(status)", "observed_at": 1700000000, "expires_at": 1700000030, "source_current": true,
          "selected": {"id": "local", "tool": "demo-agent", "provider": "local-service",
                       "model": "demo-coder", "cost_class": "zero_incremental", "reason": "Fresh local evidence"},
          "candidates": [{"id": "local", "tool": "demo-agent", "provider": "local-service",
                          "model": "demo-coder", "cost_class": "zero_incremental", "eligible": true,
                          "reasons": ["Fresh probe"], "rank": 1},
                         {"id": "other", "tool": "other-agent", "provider": "other-service",
                          "model": "other-coder", "cost_class": "unknown", "eligible": false,
                          "reasons": ["Cost unknown"], "rank": null}],
          "holds": [], "reasons": ["Source preference order"], "source": "http://127.0.0.1:8080/api/engines",
          "execution_authorized": false
        }
        """.data(using: .utf8)!
        return try TaskrivetJSON.decode(RoutingEnvelope.self, from: data)
    }

    private func link(task: String, ticket: String) -> LinkRow {
        LinkRow(ticketKey: ticket, taskId: task, taskStatus: "ready", origin: "http://127.0.0.1:8080",
                holds: [], failures: 0)
    }

    private func detail(task: String) -> DetailEnvelope {
        DetailEnvelope(task: DetailTask(id: task, objective: "Synthetic work", status: "ready"))
    }

    func testRouteDecodingAndExpiry() throws {
        var value = try route()
        XCTAssertNil(value.displayError(for: "DEMO-7"))
        XCTAssertEqual(value.selected?.provider, "local-service")
        XCTAssertEqual(value.selected?.costClass, "zero_incremental")
        XCTAssertEqual(value.candidates[0].rank, 1)
        XCTAssertNil(value.candidates[1].rank)
        XCTAssertFalse(value.executionAuthorized)
        XCTAssertTrue(value.isCurrent(at: 1700000010))
        XCTAssertFalse(value.isCurrent(at: 1700000030))
        XCTAssertFalse(value.isCurrent(at: 1699999980))
        value.sourceCurrent = false
        XCTAssertFalse(value.isCurrent(at: 1700000010), "A future expiry cannot make a stale source current")
        value.sourceCurrent = nil
        XCTAssertFalse(value.isCurrent(at: 1700000010), "Older responses without explicit source freshness stay unknown")
        value.sourceCurrent = true
        value.expiresAt = nil
        XCTAssertFalse(value.isCurrent(at: 1700000010))
        value.status = "unavailable"
        value.selected = nil
        value.candidates = []
        XCTAssertNil(value.displayError(for: "DEMO-7"))
    }

    func testRouteDisplayRejectsWrongIdentityAndAuthority() throws {
        var value = try route()
        XCTAssertNotNil(value.displayError(for: "DEMO-8"))
        XCTAssertNil(value.displayError(for: "DEMO-7", origin: "http://127.0.0.1:8080/"))
        XCTAssertNotNil(value.displayError(for: "DEMO-7", origin: "http://127.0.0.1:8081"))
        value.executionAuthorized = true
        XCTAssertNotNil(value.displayError(for: "DEMO-7"))
        value.executionAuthorized = false
        value.schema = "future-schema"
        XCTAssertNotNil(value.displayError(for: "DEMO-7"))
        value.schema = "taskrivet.route.v1"
        value.selected = nil
        XCTAssertNotNil(value.displayError(for: "DEMO-7"))
    }

    @MainActor
    func testInspectorDiscardsOldRefreshAfterSelectionChangesAndReturns() {
        let state = AppState()
        state.select(task: "a")
        let oldRefresh = state.beginDetailRead(task: "a")
        state.applyDetail(.success(detail(task: "a")), request: oldRefresh)
        XCTAssertEqual(state.detail?.task.id, "a")
        state.select(task: "b")
        XCTAssertNil(state.detail)
        state.select(task: "a")
        state.applyDetail(.success(detail(task: "a")), request: oldRefresh)
        XCTAssertNil(state.detail, "A → B → A must not restore the earlier selection's response")
        state.applyDetail(.failure(.timedOut), request: oldRefresh)
        XCTAssertNil(state.detailError)
    }

    @MainActor
    func testInspectorLatestRequestWinsAndRejectsWrongTask() {
        let state = AppState()
        state.select(task: "a")
        let old = state.beginDetailRead(task: "a")
        let newest = state.beginDetailRead(task: "a")
        state.applyDetail(.success(detail(task: "a")), request: newest)
        state.applyDetail(.failure(.timedOut), request: old)
        XCTAssertEqual(state.detail?.task.id, "a")
        XCTAssertNil(state.detailError)
        state.applyDetail(.success(detail(task: "b")), request: newest)
        XCTAssertNil(state.detail)
        XCTAssertNotNil(state.detailError)
    }

    @MainActor
    func testRoutingSerializesReadsAndDiscardsOldSelection() throws {
        let state = AppState()
        state.links = [link(task: "a", ticket: "DEMO-7"), link(task: "b", ticket: "DEMO-8")]
        state.select(task: "a")
        let request = try XCTUnwrap(state.beginRoutingRead())
        XCTAssertNil(state.beginRoutingRead(), "A second route process must not overlap")
        state.select(task: "b")
        XCTAssertNil(state.routing)
        XCTAssertTrue(state.applyRouting(.success(try route()), request: request))
        XCTAssertNil(state.routing)
        XCTAssertFalse(state.routingRefreshing)
        let next = try XCTUnwrap(state.beginRoutingRead())
        XCTAssertEqual(next.ticket, "DEMO-8")
        XCTAssertFalse(state.applyRouting(.success(try route(key: "DEMO-8")), request: next))
        XCTAssertEqual(state.routing?.ticket.key, "DEMO-8")
    }

    @MainActor
    func testRoutingDiscardsABASelectionAndClearsFailedRecommendation() throws {
        let state = AppState()
        state.links = [link(task: "a", ticket: "DEMO-7"), link(task: "b", ticket: "DEMO-8")]
        state.select(task: "a")
        let old = try XCTUnwrap(state.beginRoutingRead())
        state.select(task: "b")
        state.select(task: "a")
        XCTAssertTrue(state.applyRouting(.success(try route()), request: old))
        XCTAssertNil(state.routing)
        let current = try XCTUnwrap(state.beginRoutingRead())
        state.applyRouting(.success(try route()), request: current)
        XCTAssertNotNil(state.routing)
        let failed = try XCTUnwrap(state.beginRoutingRead())
        state.applyRouting(.failure(.timedOut), request: failed)
        XCTAssertNil(state.routing)
        XCTAssertNotNil(state.routingError)
    }

    @MainActor
    func testRoutingPinsOriginalOriginAndRejectsChangedOrMissingOrigin() throws {
        let state = AppState()
        state.links = [link(task: "a", ticket: "DEMO-7")]
        state.select(task: "a")
        let original = try XCTUnwrap(state.beginRoutingRead())
        XCTAssertEqual(original.origin, "http://127.0.0.1:8080")
        XCTAssertEqual(CoreBridge.ticketRouteArguments(key: original.ticket, origin: original.origin),
                       ["ticket-route", "DEMO-7", "--url", "http://127.0.0.1:8080"])
        state.links[0].origin = "http://127.0.0.1:8081"
        XCTAssertTrue(state.applyRouting(.success(try route()), request: original))
        XCTAssertNil(state.routing)
        let changed = try XCTUnwrap(state.beginRoutingRead())
        state.applyRouting(.success(try route()), request: changed)
        XCTAssertNil(state.routing, "A response from the old source must not appear under the new source")
        XCTAssertNotNil(state.routingError)
        state.links[0].origin = nil
        XCTAssertNil(state.beginRoutingRead(), "Missing original origin must not fall back to current config")
        XCTAssertTrue(state.routingError?.contains("no source origin") == true)
    }
}
