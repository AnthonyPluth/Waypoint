import Foundation
import WebKit

enum WebLaunch: Equatable {
    case server(URL)
    case cachedPage(URL)
    case signedOut
    case failed(String)
}

actor ServerSession {
    static let shared = ServerSession()

    private static let serverKey = "server"
    private static let tokensKey = "tokens"
    private static let openKey = "open"
    private static let revocationsKey = "pending-revocations"

    private(set) var server: URL?
    private var tokens: Tokens?
    private var open = false
    private var webSessionExpiresAt: Date?
    private let renewals = SingleFlight<String>()
    private let offline: OfflineSync
    private let api: ServerAPI
    private let installCookie: @Sendable (WebCookie, URL) async throws -> Void

    init(offline: OfflineSync = .shared,
         api: ServerAPI = LiveServerAPI(),
         restoring: (server: URL, tokens: Tokens?)? = nil,
         installCookie: @escaping @Sendable (WebCookie, URL) async throws -> Void = { try await ServerSession.install($0, for: $1) }) {
        self.offline = offline
        self.api = api
        self.installCookie = installCookie
        if let restoring {
            server = restoring.server
            tokens = restoring.tokens
            return
        }
        if let data = Keychain.get(Self.serverKey), let text = String(data: data, encoding: .utf8) {
            server = URL(string: text)
        }
        open = Keychain.get(Self.openKey) != nil
        if let data = Keychain.get(Self.tokensKey) {
            tokens = try? JSONDecoder().decode(Tokens.self, from: data)
        }
    }

    var isConnected: Bool { server != nil && (open || tokens != nil) }

    func connect(to address: String, signIn: @MainActor () -> SignIn) async throws {
        let url = try ServerClient.normalize(address)
        if try await ServerClient.opensWithoutSignIn(url) {
            await offline.serverChanged(from: server, to: url)
            keep(server: url, tokens: nil)
            open = true
            Keychain.set(Data("1".utf8), for: Self.openKey)
            return
        }
        let endpoints = try await ServerClient.endpoints(url)
        let fresh = try await signIn().run(endpoints: endpoints)
        await offline.serverChanged(from: server, to: url)
        keep(server: url, tokens: fresh)
        open = false
        Keychain.remove(Self.openKey)
    }

    func accessToken() async throws -> String {
        guard server != nil, let current = tokens else { throw ServerError.signedOut }
        if current.expiresAt.timeIntervalSinceNow > 60 { return current.accessToken }
        return try await renewals.run { [self] in try await renewAccessToken() }
    }

    func offlineBearer() async throws -> String? {
        if open { return nil }
        return try await accessToken()
    }

    private func renewAccessToken() async throws -> String {
        guard let server, let current = tokens else { throw ServerError.signedOut }
        if current.expiresAt.timeIntervalSinceNow > 60 { return current.accessToken }
        let endpoints = try await api.endpoints(server)
        do {
            let renewed = try await api.refresh(current.refreshToken, endpoints: endpoints)
            guard self.server == server, tokens == current else { throw ServerError.signedOut }
            keep(server: server, tokens: renewed)
            return renewed.accessToken
        } catch ServerError.signedOut {
            if self.server == server, tokens == current { forgetTokens() }
            throw ServerError.signedOut
        }
    }

    func prepareWebView() async throws -> URL {
        guard let server else { throw ServerError.signedOut }
        if open { return server }
        let cookie = try await api.webCookie(server, accessToken: try await accessToken())
        try await installCookie(cookie, server)
        webSessionExpiresAt = Date().addingTimeInterval(TimeInterval(cookie.maxAge))
        return server
    }

    func launchWebView(gate: OfflineGate = .shared, patience: UInt64 = 5_000_000_000) async -> WebLaunch {
        let hasCachedPage = server.map { gate.canShowCachedPage(for: $0) } ?? false
        do {
            if let ready = try await prepareWebView(within: hasCachedPage ? patience : nil) { return .server(ready) }
        } catch ServerError.signedOut {
            await signOut()
            return .signedOut
        } catch ServerError.offline(let why) {
            return cachedPage(gate: gate) ?? .failed(ServerError.offline(why).localizedDescription)
        } catch {
            return .failed(error.localizedDescription)
        }
        return cachedPage(gate: gate) ?? .failed(ServerError.offline("the server did not answer").localizedDescription)
    }

    private func cachedPage(gate: OfflineGate) -> WebLaunch? {
        guard let server, gate.canShowCachedPage(for: server) else { return nil }
        return .cachedPage(server)
    }

    private func prepareWebView(within patience: UInt64?) async throws -> URL? {
        guard let patience else { return try await prepareWebView() }
        return try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<URL?, Error>) in
            let once = ResumeOnce(continuation)
            Task {
                do {
                    once.resume(.success(try await self.prepareWebView()))
                } catch {
                    once.resume(.failure(error))
                }
            }
            Task {
                try? await Task.sleep(nanoseconds: patience)
                once.resume(.success(nil))
            }
        }
    }

    func renewForReturn() async -> Bool {
        guard webSessionNeedsRenewal() else { return true }
        do {
            _ = try await prepareWebView()
            return true
        } catch ServerError.signedOut {
            NotificationCenter.default.post(name: .webViewUnauthorized, object: nil)
            return false
        } catch {
            return false
        }
    }

    func webSessionNeedsRenewal(now: Date = Date()) -> Bool {
        guard server != nil, !open else { return false }
        return WebSessionClock.needsRenewal(expiresAt: webSessionExpiresAt, now: now)
    }

    func signOut() async {
        if let server, let current = tokens {
            savePending(PendingRevocation.adding(PendingRevocation(server: server.absoluteString, refreshToken: current.refreshToken), to: pendingRevocations()))
        }
        let host = server?.host
        server = nil
        open = false
        forgetTokens()
        Keychain.remove(Self.openKey)
        Keychain.remove(Self.serverKey)
        webSessionExpiresAt = nil
        await offline.signedOut()
        Task { await retryPendingRevocations() }
        await Self.clearWebData(host: host)
    }

    func retryPendingRevocations() async {
        for pending in pendingRevocations() {
            guard let server = URL(string: pending.server), let endpoints = try? await api.endpoints(server) else {
                continue
            }
            if await api.revoke(pending.refreshToken, endpoints: endpoints) {
                savePending(PendingRevocation.removing(pending, from: pendingRevocations()))
            }
        }
    }

    private func pendingRevocations() -> [PendingRevocation] {
        guard let data = Keychain.get(Self.revocationsKey) else { return [] }
        return (try? JSONDecoder().decode([PendingRevocation].self, from: data)) ?? []
    }

    private func savePending(_ list: [PendingRevocation]) {
        if list.isEmpty {
            Keychain.remove(Self.revocationsKey)
        } else if let data = try? JSONEncoder().encode(list) {
            Keychain.set(data, for: Self.revocationsKey)
        }
    }

    private func keep(server: URL, tokens: Tokens?) {
        self.server = server
        self.tokens = tokens
        Keychain.set(Data(server.absoluteString.utf8), for: Self.serverKey)
        if let tokens, let data = try? JSONEncoder().encode(tokens) {
            Keychain.set(data, for: Self.tokensKey)
        }
    }

    private func forgetTokens() {
        tokens = nil
        Keychain.remove(Self.tokensKey)
    }

    @MainActor
    static func install(_ cookie: WebCookie, for server: URL) async throws {
        var properties: [HTTPCookiePropertyKey: Any] = [
            .domain: server.host ?? "", .path: "/", .name: cookie.name, .value: cookie.value,
            .expires: Date().addingTimeInterval(TimeInterval(cookie.maxAge)),
            .sameSitePolicy: HTTPCookieStringPolicy.sameSiteLax,
            HTTPCookiePropertyKey("HttpOnly"): "TRUE",
        ]
        if cookie.secure { properties[.secure] = "TRUE" }
        guard let made = HTTPCookie(properties: properties) else { throw ServerError.notWaypoint }
        await WKWebsiteDataStore.default().httpCookieStore.setCookie(made)
    }

    @MainActor
    private static func clearWebData(host: String?) async {
        let store = WKWebsiteDataStore.default()
        let records = await store.dataRecords(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes())
        let mine = records.filter { host != nil && WebDataScope.covers(recordName: $0.displayName, host: host!) }
        await store.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), for: mine)
    }
}

enum WebDataScope {
    static func covers(recordName: String, host: String) -> Bool {
        let name = recordName.lowercased()
        let host = host.lowercased()
        guard !name.isEmpty, !host.isEmpty else { return false }
        return name == host || host.hasSuffix("." + name) || name.hasSuffix("." + host)
    }
}

struct PendingRevocation: Codable, Equatable {
    var server: String
    var refreshToken: String

    static func adding(_ new: PendingRevocation, to list: [PendingRevocation]) -> [PendingRevocation] {
        list.contains(new) ? list : list + [new]
    }

    static func removing(_ done: PendingRevocation, from list: [PendingRevocation]) -> [PendingRevocation] {
        list.filter { $0 != done }
    }
}

final class ResumeOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<URL?, Error>?

    init(_ continuation: CheckedContinuation<URL?, Error>) {
        self.continuation = continuation
    }

    func resume(_ result: Result<URL?, Error>) {
        lock.lock()
        let held = continuation
        continuation = nil
        lock.unlock()
        held?.resume(with: result)
    }
}

actor SingleFlight<Value: Sendable> {
    private var inFlight: Task<Value, Error>?

    func run(_ work: @escaping @Sendable () async throws -> Value) async throws -> Value {
        if let inFlight { return try await inFlight.value }
        let task = Task { try await work() }
        inFlight = task
        defer { inFlight = nil }
        return try await task.value
    }
}

enum WebSessionClock {
    static let margin: TimeInterval = 300

    static func needsRenewal(expiresAt: Date?, now: Date) -> Bool {
        guard let expiresAt else { return true }
        return expiresAt.timeIntervalSince(now) <= margin
    }
}
