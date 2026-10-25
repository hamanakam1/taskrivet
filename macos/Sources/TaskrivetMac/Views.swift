import SwiftUI

/// Status dot color shared across rows. "ready" is idle-but-claimable,
/// not running work; nothing here implies authorization.
func taskStatusColor(_ status: String) -> Color {
    switch status {
    case "running": return .green
    case "review": return .orange
    case "blocked": return .red
    case "ready": return .blue
    case "accepted": return .gray
    default: return .secondary
    }
}

// MARK: - Sidebar

struct SidebarView: View {
    @ObservedObject var state: AppState
    @Binding var selection: String?

    var body: some View {
        List(selection: $selection) {
            Section("Ticket loop") {
                if state.links.isEmpty {
                    Text("No imported tickets")
                        .foregroundStyle(.secondary)
                        .font(.callout)
                }
                ForEach(state.links) { link in
                    LinkRowView(link: link)
                        .tag(link.taskId)
                }
            }
            Section("Ledger tasks") {
                ForEach(state.tasks) { task in
                    TaskRowView(task: task)
                        .tag(task.id)
                }
            }
            Section("Session terminals") {
                if state.sessionService != "running" {
                    Text("Session service: \(state.sessionService)")
                        .foregroundStyle(.secondary)
                        .font(.callout)
                }
                ForEach(state.terminals) { terminal in
                    TerminalRowView(terminal: terminal)
                }
            }
        }
        .listStyle(.sidebar)
        .environmentObject(state)
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 4) {
                if let provenance = state.provenance {
                    Text(provenance)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 10)
                }
                if let refreshed = state.lastRefresh {
                    Text("Refreshed \(taskrivetTime(refreshed.timeIntervalSince1970))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 10)
                }
            }
            .padding(.vertical, 6)
        }
    }
}

struct LinkRowView: View {
    let link: LinkRow

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Circle().fill(taskStatusColor(link.taskStatus)).frame(width: 8, height: 8)
                Text(link.ticketKey).font(.headline)
                Spacer()
                if let handback = link.handback {
                    HandbackBadge(handback: handback)
                }
            }
            Text(link.title ?? link.taskId)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            HStack(spacing: 6) {
                if !link.unacknowledgedHolds.isEmpty {
                    Label("\(link.unacknowledgedHolds.count) hold(s)", systemImage: "hand.raised.fill")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
                if let session = link.session {
                    Label(session.status, systemImage: "clock")
                        .font(.caption2)
                        .foregroundStyle(session.status == "active" ? .green : .secondary)
                    if session.status == "active" {
                        Text("\(session.leaseRemainingSeconds)s lease")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                if link.failures > 0 {
                    Label("\(link.failures)", systemImage: "exclamationmark.triangle")
                        .font(.caption2)
                        .foregroundStyle(.red)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

struct HandbackBadge: View {
    let handback: LinkHandback

    var body: some View {
        let (label, color): (String, Color) = {
            switch handback.status {
            case "delivered": return ("delivered", .green)
            case "pending": return ("pending", .orange)
            default: return (handback.status, .red)
            }
        }()
        Text(label)
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
            .help(handback.lastError ?? "attempts: \(handback.attempts)")
    }
}

struct TaskRowView: View {
    let task: TaskRow

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(taskStatusColor(task.status)).frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 2) {
                Text(task.id).font(.callout)
                Text(task.objective).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }
}

struct TerminalRowView: View {
    @EnvironmentObject var state: AppState
    let terminal: TerminalRecord

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: terminal.state == "running" ? "terminal.fill" : "terminal")
                .foregroundStyle(terminal.state == "running" ? .green : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(terminal.title ?? terminal.command ?? String(terminal.id.prefix(8)))
                    .font(.callout)
                if let task = terminal.task {
                    Text(task).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if terminal.state == "running" {
                Button("Attach") { state.attach(to: terminal) }
                    .buttonStyle(.borderless)
                    .font(.caption)
            }
        }
    }
}

// MARK: - Inspector

struct InspectorView: View {
    @ObservedObject var state: AppState

    var body: some View {
        if let error = state.detailError {
            ContentUnavailableView("Detail unavailable", systemImage: "exclamationmark.triangle",
                                   description: Text(error))
        } else if let detail = state.detail {
            DetailView(detail: detail, link: state.links.first { $0.taskId == detail.task.id })
        } else {
            ContentUnavailableView("Select a task", systemImage: "sidebar.left",
                                   description: Text("Pick a ticket link or a ledger task to inspect its ledger record."))
        }
    }
}

struct DetailView: View {
    let detail: DetailEnvelope
    let link: LinkRow?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                taskSection
                if let link { ticketSection(link) }
                if let session = detail.session { sessionSection(session) }
                if let claims = detail.claims, !claims.isEmpty { claimsSection(claims) }
                if let checkpoints = detail.checkpoints, !checkpoints.isEmpty { checkpointsSection(checkpoints) }
                if let failures = detail.failures, !failures.isEmpty { failuresSection(failures) }
                if let context = detail.context, !context.isEmpty { contextSection(context) }
                if let events = detail.events, !events.isEmpty { eventsSection(events) }
                if let provenance = detail.provenance {
                    Text(provenance)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    var taskSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Circle().fill(taskStatusColor(detail.task.status)).frame(width: 10, height: 10)
                Text(detail.task.id).font(.title3.bold())
                Spacer()
                Text(detail.task.status).foregroundStyle(.secondary)
            }
            Text(detail.task.objective).font(.body)
            if let acceptance = detail.task.acceptance {
                Text("Acceptance: \(acceptance)")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 12) {
                if let budget = detail.task.tokenBudget {
                    let used = detail.task.reportedTokens ?? 0
                    Label("\(used) / \(budget) reported tokens (self-reported)", systemImage: "gauge")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let pack = detail.pack {
                    Label("\(pack.items) context items, \(pack.bytes ?? 0) bytes", systemImage: "shippingbox")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            if let keys = detail.task.scope, !keys.isEmpty {
                Text("Scope keys: \(keys.joined(separator: ", "))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    func ticketSection(_ link: LinkRow) -> some View {
        GroupBox("Ticket \(link.ticketKey)") {
            VStack(alignment: .leading, spacing: 6) {
                if let title = link.title { Text(title).font(.callout) }
                if let revision = link.revision {
                    Text("Bound revision \(revision.prefix(12))…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if !link.holds.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(link.holds, id: \.self) { hold in
                            let acked = link.acknowledged?.contains(hold) ?? false
                            Label(hold, systemImage: acked ? "checkmark.circle" : "hand.raised")
                                .font(.caption)
                                .foregroundStyle(acked ? Color.secondary : Color.orange)
                        }
                    }
                }
                if let handback = link.handback {
                    HStack {
                        Text("Report:").font(.caption).foregroundStyle(.secondary)
                        HandbackBadge(handback: handback)
                        if let delivered = handback.delivered {
                            Text(taskrivetTime(delivered)).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                if let agent = link.agent {
                    HStack(spacing: 8) {
                        Label(agent.tool ?? "agent", systemImage: "terminal")
                            .font(.caption)
                        if let runDir = agent.runDir {
                            Text(runDir).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func sessionSection(_ session: DetailSession) -> some View {
        GroupBox("Session") {
            VStack(alignment: .leading, spacing: 4) {
                Label(session.status, systemImage: "clock")
                if let owner = session.owner {
                    Text("Owner: \(owner)").font(.caption).foregroundStyle(.secondary)
                }
                Text("Reported tokens: \(session.tokens ?? 0) (self-reported, not billing)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func claimsSection(_ claims: [DetailClaim]) -> some View {
        GroupBox("Scope claims held by other tasks") {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(claims) { claim in
                    Text("\(claim.task) (\(claim.status)): \(claim.sharedKeys.joined(separator: ", "))")
                        .font(.caption)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func checkpointsSection(_ checkpoints: [DetailCheckpoint]) -> some View {
        GroupBox("Checkpoints (operator records)") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(checkpoints) { checkpoint in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(checkpoint.summary).font(.callout)
                        if let next = checkpoint.nextStep {
                            Text("Next: \(next)").font(.caption).foregroundStyle(.secondary)
                        }
                        Text(taskrivetTime(checkpoint.created)).font(.caption2).foregroundStyle(.tertiary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func failuresSection(_ failures: [DetailFailure]) -> some View {
        GroupBox("Failures") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(failures) { failure in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(failure.category ?? "failure").font(.callout.bold())
                            if let occurrences = failure.occurrences, occurrences > 1 {
                                Text("×\(occurrences)").font(.caption).foregroundStyle(.red)
                            }
                        }
                        Text(failure.summary).font(.caption)
                        Text(taskrivetTime(failure.created)).font(.caption2).foregroundStyle(.tertiary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func contextSection(_ context: [DetailContextItem]) -> some View {
        GroupBox("Bounded context") {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(context) { item in
                    HStack {
                        Text(item.source).font(.caption)
                        Spacer()
                        Text("\(item.bytes ?? 0) B").font(.caption2).foregroundStyle(.secondary)
                        if item.expired == true {
                            Text("expired").font(.caption2).foregroundStyle(.red)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func eventsSection(_ events: [DetailEvent]) -> some View {
        GroupBox("Ledger events") {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(events.prefix(20)) { event in
                    HStack(alignment: .top) {
                        Text(event.type).font(.caption.monospaced())
                        Spacer()
                        Text(taskrivetTime(event.created)).font(.caption2).foregroundStyle(.tertiary)
                    }
                    if let data = event.data, !data.isEmpty {
                        Text(JSONValue.object(data).rendered)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
