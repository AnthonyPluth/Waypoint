import Foundation

struct OfflineSettings: @unchecked Sendable {
    static let key = "offlineSaving"

    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var isOn: Bool { defaults.bool(forKey: Self.key) }

    func set(_ on: Bool) {
        defaults.set(on, forKey: Self.key)
    }
}

protocol OfflineFetching: Sendable {
    func fetch(server: URL, bearer: String?) async throws -> (data: Data, status: Int)
}

struct LiveOfflineFetching: OfflineFetching {
    func fetch(server: URL, bearer: String?) async throws -> (data: Data, status: Int) {
        let (data, response) = try await ServerClient.get(server.appendingPathComponent("api/offline"), bearer: bearer)
        return (data, response.statusCode)
    }
}

actor OfflineSync {
    static let supportedVersion = 1

    static let shared = OfflineSync(
        server: { await ServerSession.shared.server },
        bearer: { try await ServerSession.shared.offlineBearer() })

    enum Outcome: Equatable {
        case off
        case noServer
        case saved
        case unknownVersion
        case unauthorized
        case failed
        case superseded
    }

    private let store: OfflineStore
    private let settings: OfflineSettings
    private let fetching: OfflineFetching
    private let currentServer: @Sendable () async -> URL?
    private let currentBearer: @Sendable () async throws -> String?
    private var generation = 0

    init(store: OfflineStore = .shared,
         settings: OfflineSettings = OfflineSettings(),
         fetching: OfflineFetching = LiveOfflineFetching(),
         server: @escaping @Sendable () async -> URL?,
         bearer: @escaping @Sendable () async throws -> String?) {
        self.store = store
        self.settings = settings
        self.fetching = fetching
        self.currentServer = server
        self.currentBearer = bearer
    }

    @discardableResult
    func sync() async -> Outcome {
        guard settings.isOn else { return .off }
        guard let server = await currentServer() else {
            purge()
            return .noServer
        }
        let started = generation
        let reply: (data: Data, status: Int)
        do {
            reply = try await fetching.fetch(server: server, bearer: try await currentBearer())
        } catch ServerError.signedOut {
            purge()
            return .unauthorized
        } catch {
            return .failed
        }
        guard started == generation, settings.isOn else { return .superseded }
        if reply.status == 401 || reply.status == 403 {
            purge()
            return .unauthorized
        }
        guard reply.status == 200 else { return .failed }
        guard Self.version(of: reply.data) == Self.supportedVersion else { return .unknownVersion }
        do {
            try store.save(reply.data, version: Self.supportedVersion, for: server)
            return .saved
        } catch {
            return .failed
        }
    }

    func purge() {
        generation += 1
        try? store.purgeAll()
    }

    func setSaving(_ on: Bool) {
        settings.set(on)
        if !on { purge() }
    }

    func remove() {
        purge()
    }

    func serverChanged(from old: URL?, to new: URL) {
        guard let old, Endpoints.canonical(old) != Endpoints.canonical(new) else { return }
        purge()
    }

    private static func version(of data: Data) -> Int? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return object["version"] as? Int
    }
}
