import Foundation

/// Minimal JSON value for ledger payloads whose shape is not part of the
/// stable CLI contract (event data, checkpoint extras). Rendering only.
indirect enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let n = try? c.decode(Double.self) { self = .number(n); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        if let a = try? c.decode([JSONValue].self) { self = .array(a); return }
        self = .object(try c.decode([String: JSONValue].self))
    }

    /// Single-line, compact rendering for inspector rows.
    var rendered: String {
        switch self {
        case .string(let s): return s
        case .number(let n):
            return n.rounded() == n ? String(Int(n)) : String(n)
        case .bool(let b): return b ? "true" : "false"
        case .null: return "null"
        case .array(let a): return "[" + a.map { $0.rendered }.joined(separator: ", ") + "]"
        case .object(let o):
            let inner = o.keys.sorted().map { "\($0): \(o[$0]!.rendered)" }.joined(separator: ", ")
            return "{" + inner + "}"
        }
    }
}

// MARK: - status --format json

struct TaskRow: Codable, Equatable, Identifiable {
    /// `status` reports scope as a JSON-encoded string; `detail` reports an
    /// array. Kept as the raw string here and decoded on demand.
    var id: String
    var objective: String
    var acceptance: String?
    var kind: String?
    var scope: String?
    var status: String
    var tokenBudget: Int?
    var created: Double?

    var scopeKeys: [String] {
        guard let scope,
              let data = scope.data(using: .utf8),
              let keys = try? JSONDecoder().decode([String].self, from: data)
        else { return [] }
        return keys
    }
}

struct StatusEnvelope: Codable, Equatable {
    var tasks: [TaskRow]
}

// MARK: - links --format json

struct LinkSession: Codable, Equatable {
    var id: String
    var owner: String?
    var status: String
    var leaseRemainingSeconds: Int
    var reportedTokens: Int?
}

struct LinkCheckpoint: Codable, Equatable {
    var summary: String
    var nextStep: String?
    var created: Double
}

struct LinkFailure: Codable, Equatable {
    var category: String?
    var summary: String
    var created: Double
}

struct LinkHandback: Codable, Equatable {
    var id: String
    var status: String
    var attempts: Int
    var lastError: String?
    var updated: Double?
    var delivered: Double?
}

struct LinkAgent: Codable, Equatable {
    var tool: String?
    var terminal: String?
    var session: String?
    var launched: Double?
    var runDir: String?
}

struct LinkRow: Codable, Equatable, Identifiable {
    var ticketKey: String
    var taskId: String
    var taskStatus: String
    var title: String?
    var revision: String?
    var imported: Double?
    var refreshed: Double?
    var holds: [String]
    var acknowledged: [String]?
    var session: LinkSession?
    var checkpoint: LinkCheckpoint?
    var failures: Int
    var lastFailure: LinkFailure?
    var handback: LinkHandback?
    var agent: LinkAgent?

    var id: String { taskId }

    var unacknowledgedHolds: [String] {
        let acked = Set(acknowledged ?? [])
        return holds.filter { !acked.contains($0) }
    }
}

struct LinksEnvelope: Codable, Equatable {
    var schema: Int
    var generatedAt: Double
    var links: [LinkRow]
    var provenance: String?
}

// MARK: - sessions --format json

struct TerminalRecord: Codable, Equatable, Identifiable {
    var id: String
    var title: String?
    var kind: String?
    var ref: String?
    var task: String?
    var session: String?
    var state: String
    var exitCode: Int?
    var pid: Int?
    var cwd: String?
    var command: String?
    var outputBytes: Int?
    var lastLine: String?
}

struct SessionsEnvelope: Codable, Equatable {
    /// "running", "stopped", or an unavailable marker from the CLI.
    var service: String
    var implementation: String?
    var directory: String?
    var terminals: [TerminalRecord]?
}

// MARK: - detail --task <id> --format json

struct DetailTask: Codable, Equatable {
    var id: String
    var objective: String
    var acceptance: String?
    var kind: String?
    var scope: [String]?
    var status: String
    var tokenBudget: Int?
    var created: Double?
    var reportedTokens: Int?
    var remainingTokens: Int?
}

struct DetailSession: Codable, Equatable, Identifiable {
    var id: String
    var owner: String?
    var status: String
    var created: Double?
    var leaseUntil: Double?
    var tokens: Int?
}

struct DetailCheckpoint: Codable, Equatable, Identifiable {
    var sessionId: String?
    var summary: String
    /// Stored as a JSON-encoded string in the ledger; rendered as recorded.
    var evidence: String?
    var nextStep: String?
    var tokens: Int?
    var created: Double?

    var id: String { "\(created ?? 0)-\(summary.prefix(24))" }
}

struct DetailContextItem: Codable, Equatable, Identifiable {
    var hash: String
    var source: String
    var priority: Int?
    var expires: Double?
    var bytes: Int?
    var expired: Bool?

    var id: String { hash }
}

struct DetailFailure: Codable, Equatable, Identifiable {
    var sessionId: String?
    var category: String?
    var summary: String
    var fingerprint: String?
    var created: Double?
    /// Recurrence count for the same fingerprint across the ledger.
    var occurrences: Int?

    var id: String { "\(created ?? 0)-\(summary.prefix(24))" }
}

/// Another task claiming one or more of the same scope keys.
struct DetailClaim: Codable, Equatable, Identifiable {
    var task: String
    var status: String
    var sharedKeys: [String]

    var id: String { task }
}

/// Size summary of the bounded context packet the CLI would hand to an agent.
struct DetailPack: Codable, Equatable {
    var bytes: Int?
    var items: Int
    var omitted: [JSONValue]?
    var error: String?
}

struct DetailEvent: Codable, Equatable, Identifiable {
    var seq: Int
    var type: String
    var created: Double?
    var data: [String: JSONValue]?

    var id: Int { seq }
}

struct DetailEnvelope: Codable, Equatable {
    var task: DetailTask
    var session: DetailSession?
    var sessions: [DetailSession]?
    var checkpoints: [DetailCheckpoint]?
    var context: [DetailContextItem]?
    var failures: [DetailFailure]?
    var events: [DetailEvent]?
    var claims: [DetailClaim]?
    var pack: DetailPack?
    var provenance: String?
}

// MARK: - launchers --format json

struct Launcher: Codable, Equatable, Identifiable {
    var tool: String
    var status: String
    var detail: String?

    var id: String { tool }
}

struct LaunchersEnvelope: Codable, Equatable {
    var launchers: [Launcher]
}

// MARK: - doctor --format json

struct DoctorCheck: Codable, Equatable, Identifiable {
    var check: String
    var status: String
    var detail: String?

    var id: String { check }
}

struct DoctorEnvelope: Codable, Equatable {
    /// "ok", "warn", or "error" for the whole run.
    var status: String
    var checks: [DoctorCheck]
}

// MARK: - Shared decoding

enum TaskrivetJSON {
    static func decoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try decoder().decode(type, from: data)
    }
}

/// Shared absolute-time rendering for ledger epoch timestamps.
func taskrivetTime(_ epoch: Double?) -> String {
    guard let epoch else { return "never" }
    let date = Date(timeIntervalSince1970: epoch)
    let fmt = DateFormatter()
    fmt.dateStyle = .short
    fmt.timeStyle = .medium
    return fmt.string(from: date)
}
