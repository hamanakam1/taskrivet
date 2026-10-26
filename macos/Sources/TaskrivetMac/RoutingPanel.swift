import SwiftUI

struct RoutingPanel: View {
    @ObservedObject var state: AppState
    let link: LinkRow

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                if let error = state.routingError {
                    Label("Routing unavailable", systemImage: "exclamationmark.triangle")
                        .font(.callout.bold())
                        .foregroundStyle(.orange)
                    Text(error).font(.caption).textSelection(.enabled)
                } else if let route = state.routing, let origin = link.origin,
                          route.displayError(for: link.ticketKey, origin: origin) == nil {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        routeSummary(route, now: context.date.timeIntervalSince1970)
                    }
                } else if state.routingRefreshing {
                    ProgressView("Reading routing evidence…").font(.caption)
                } else {
                    Text("No routing evidence has been read for this ticket.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Text("Read-only recommendation. Launch and ticket acceptance remain separate operator actions.")
                    .font(.caption2).foregroundStyle(.secondary)
                Text("Refreshes every 30 seconds while this workspace is open.")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            HStack {
                Label("Model and provider", systemImage: "arrow.triangle.branch")
                Spacer()
                Button {
                    state.refreshRouting()
                } label: {
                    Label("Refresh routing", systemImage: "arrow.clockwise")
                        .labelStyle(.iconOnly)
                }
                .buttonStyle(.borderless)
                .disabled(state.routingRefreshing || state.bridge == nil)
                .help("Read the current ticket and model routing evidence. Launches nothing.")
            }
        }
    }

    @ViewBuilder
    private func routeSummary(_ route: RoutingEnvelope, now: Double) -> some View {
        let current = route.isCurrent(at: now)
        HStack {
            Label(statusText(route, current: current),
                  systemImage: route.status == "recommended" && current ? "checkmark.circle" : "hand.raised")
                .font(.callout.bold())
                .foregroundStyle(route.status == "recommended" && current ? Color.green : Color.orange)
            if state.routingRefreshing {
                ProgressView().controlSize(.small)
            }
        }
        if let selected = route.selected {
            VStack(alignment: .leading, spacing: 4) {
                Text(selected.model).font(.headline).textSelection(.enabled)
                Text("\(selected.provider) · \(selected.tool)").font(.callout)
                Text(costLabel(selected.costClass)).font(.caption).foregroundStyle(.secondary)
                Text(selected.reason).font(.caption).textSelection(.enabled)
            }
        }
        if !route.holds.isEmpty { reasons("Holds", rows: route.holds, color: .orange) }
        if !route.reasons.isEmpty { reasons("Routing evidence", rows: route.reasons, color: .secondary) }
        if let revision = link.revision, revision != route.ticket.revision {
            Label("The source ticket changed since this task was imported. Review the current ticket before starting work.",
                  systemImage: "arrow.triangle.2.circlepath")
                .font(.caption).foregroundStyle(.orange)
        }
        VStack(alignment: .leading, spacing: 2) {
            Text("Read \(taskrivetTime(route.observedAt))")
            if current, let expiry = route.expiresAt {
                Text("Source snapshot expires \(taskrivetTime(expiry))")
            } else if route.sourceCurrent == true, let expiry = route.expiresAt, expiry <= now {
                Text("Source snapshot expired \(taskrivetTime(expiry))").foregroundStyle(.orange)
            } else {
                Text("Source snapshot is stale or freshness is unknown").foregroundStyle(.orange)
            }
            Text("Source: \(route.source)").textSelection(.enabled)
            Text("Ticket revision \(route.ticket.revision.prefix(12))")
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        if !route.candidates.isEmpty {
            DisclosureGroup("Routes considered (\(route.candidates.count))") {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(route.candidates) { candidate in
                        candidateView(candidate, selected: candidate.id == route.selected?.id)
                    }
                }
                .padding(.top, 6)
            }
            .font(.caption)
        }
    }

    private func candidateView(_ candidate: RouteCandidate, selected: Bool) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text(candidate.model).font(.caption.bold())
                if selected { Text("selected").foregroundStyle(.secondary) }
                Spacer()
                if let rank = candidate.rank { Text("Source rank \(rank)").foregroundStyle(.secondary) }
            }
            Text("\(candidate.provider) · \(candidate.tool) · \(costLabel(candidate.costClass))")
                .foregroundStyle(.secondary)
            Text(candidate.eligible ? "Eligible for recommendation" : "Held")
                .foregroundStyle(candidate.eligible ? Color.secondary : Color.orange)
            ForEach(Array(candidate.reasons.enumerated()), id: \.offset) { _, reason in
                Text(reason).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
    }

    private func reasons(_ title: String, rows: [String], color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption.bold())
            ForEach(Array(rows.enumerated()), id: \.offset) { _, reason in
                Text("• \(reason)").font(.caption)
            }
        }
        .foregroundStyle(color)
        .textSelection(.enabled)
    }

    private func statusText(_ route: RoutingEnvelope, current: Bool) -> String {
        switch route.status {
        case "recommended": return current ? "Recommended route" : "Recommendation needs refresh"
        case "held": return "Routing held"
        default: return "Routing unavailable"
        }
    }

    private func costLabel(_ value: String) -> String {
        switch value {
        case "zero_incremental": return "No incremental cost"
        case "paid": return "Metered cost"
        case "unknown": return "Cost unknown"
        default: return value.replacingOccurrences(of: "_", with: " ")
        }
    }
}
