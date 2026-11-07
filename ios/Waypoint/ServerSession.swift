import Foundation
import WebKit

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

    init() {
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
            keep(server: url, tokens: nil)
            open = true
            Keychain.set(Data("1".utf8), for: Self.openKey)
            return
        }
        let endpoints = try await ServerClient.endpoints(url)
        let fresh = try await signIn().run(endpoints: endpoints)
        keep(server: url, tokens: fresh)
        open = false
        Keychain.remove(Self.openKey)
    }

    func accessToken() async throws -> String {
        guard server != nil, let current = tokens else { throw ServerError.signedOut }
        if current.expiresAt.timeIntervalSinceNow > 60 { return current.accessToken }
        return try await renewals.run { [self] in try await renewAccessToken() }
    }

    private func renewAccessToken() async throws -> String {
        guard let server, let current = tokens else { throw ServerError.signedOut }
        if current.expiresAt.timeIntervalSinceNow > 60 { return current.accessToken }
        let endpoints = try await ServerClient.endpoints(server)
        do {
            let renewed = try await ServerClient.refresh(current.refreshToken, endpoints: endpoints)
            guard self.server == server else { throw ServerError.signedOut }
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
        let cookie = try await ServerClient.webCookie(server, accessToken: try await accessToken())
        try await Self.install(cookie, for: server)
        webSessionExpiresAt = Date().addingTimeInterval(TimeInterval(cookie.maxAge))
        return server
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
        Task { await retryPendingRevocations() }
        await Self.clearWebData(host: host)
    }

    func retryPendingRevocations() async {
        for pending in pendingRevocations() {
            guard let server = URL(string: pending.server), let endpoints = try? await ServerClient.endpoints(server) else {
                continue
            }
            if await ServerClient.revoke(pending.refreshToken, endpoints: endpoints) {
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
    private static func install(_ cookie: WebCookie, for server: URL) async throws {
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
