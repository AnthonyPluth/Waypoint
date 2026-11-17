import CryptoKit
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

struct PageReply: Sendable {
    let data: Data
    let status: Int
    let url: URL?
}

protocol PageFetching: Sendable {
    func get(_ url: URL) async throws -> PageReply
}

struct LivePageFetching: PageFetching {
    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 60
        return URLSession(configuration: configuration)
    }()

    func get(_ url: URL) async throws -> PageReply {
        let (data, response) = try await Self.session.data(from: url)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return PageReply(data: data, status: http.statusCode, url: http.url)
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

    enum PageOutcome: Equatable {
        case off
        case noServer
        case current
        case saved
        case failed
        case superseded
    }

    private let store: OfflineStore
    private let settings: OfflineSettings
    private let fetching: OfflineFetching
    private let pages: OfflinePages
    private let pageFetching: PageFetching
    private let currentServer: @Sendable () async -> URL?
    private let currentBearer: @Sendable () async throws -> String?
    private var generation = 0

    init(store: OfflineStore = .shared,
         settings: OfflineSettings = OfflineSettings(),
         fetching: OfflineFetching = LiveOfflineFetching(),
         pages: OfflinePages = .shared,
         pageFetching: PageFetching = LivePageFetching(),
         server: @escaping @Sendable () async -> URL?,
         bearer: @escaping @Sendable () async throws -> String?) {
        self.store = store
        self.settings = settings
        self.fetching = fetching
        self.pages = pages
        self.pageFetching = pageFetching
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

    @discardableResult
    func refreshPages(loaded assetPaths: [String]) async -> PageOutcome {
        guard settings.isOn else { return .off }
        guard let server = await currentServer() else { return .noServer }
        let started = generation
        let wanted = Array(Set(assetPaths.filter(OfflinePageFiles.isAssetPath)).sorted().prefix(OfflinePageFiles.maxAssets))
        do {
            let index = try await page(OfflinePageFiles.index, server: server)
            let build = SHA256.hash(data: index).map { String(format: "%02x", $0) }.joined()
            let sameBuild = pages.build(for: server) == build
            if sameBuild, wanted.allSatisfy({ pages.file($0, for: server) != nil }), pages.hasPage(for: server) { return .current }
            var contents: [String: Data] = [:]
            if sameBuild {
                for path in pages.paths(for: server) {
                    if let kept = pages.file(path, for: server) { contents[path] = kept }
                }
            }
            contents[OfflinePageFiles.index] = index
            for path in wanted where contents[path] == nil {
                contents[path] = try await page(path, server: server)
            }
            for path in OfflinePageFiles.shell where contents[path] == nil {
                if let data = try? await page(path, server: server) { contents[path] = data }
            }
            guard started == generation, settings.isOn else { return .superseded }
            try pages.save(contents, build: build, for: server)
            return .saved
        } catch {
            return .failed
        }
    }

    private func page(_ path: String, server: URL) async throws -> Data {
        guard var parts = URLComponents(url: server, resolvingAgainstBaseURL: false) else { throw URLError(.badURL) }
        parts.path = path
        parts.query = nil
        parts.fragment = nil
        guard let url = parts.url else { throw URLError(.badURL) }
        let reply = try await pageFetching.get(url)
        guard reply.status == 200, !reply.data.isEmpty, reply.data.count <= OfflinePageFiles.maxFileBytes,
              let final = reply.url, Endpoints.origin(final) == Endpoints.origin(server), final.path == path else {
            throw URLError(.badServerResponse)
        }
        return reply.data
    }

    func purge() {
        generation += 1
        try? store.purgeAll()
        try? pages.purgeAll()
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
