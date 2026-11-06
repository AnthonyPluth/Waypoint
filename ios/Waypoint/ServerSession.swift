import Foundation
import WebKit

actor ServerSession {
    static let shared = ServerSession()

    private static let serverKey = "server"
    private static let tokensKey = "tokens"

    private(set) var server: URL?
    private var tokens: Tokens?
    private var open = false

    init() {
        if let data = Keychain.get(Self.serverKey), let text = String(data: data, encoding: .utf8) {
            server = URL(string: text)
        }
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
            return
        }
        let endpoints = try await ServerClient.endpoints(url)
        let fresh = try await signIn().run(endpoints: endpoints)
        keep(server: url, tokens: fresh)
        open = false
    }

    func accessToken() async throws -> String {
        guard let server, let current = tokens else { throw ServerError.signedOut }
        if current.expiresAt.timeIntervalSinceNow > 60 { return current.accessToken }
        let endpoints = try await ServerClient.endpoints(server)
        do {
            let renewed = try await ServerClient.refresh(current.refreshToken, endpoints: endpoints)
            keep(server: server, tokens: renewed)
            return renewed.accessToken
        } catch ServerError.signedOut {
            forgetTokens()
            throw ServerError.signedOut
        }
    }

    func prepareWebView() async throws -> URL {
        guard let server else { throw ServerError.signedOut }
        if open { return server }
        let cookie = try await ServerClient.webCookie(server, accessToken: try await accessToken())
        try await Self.install(cookie, for: server)
        return server
    }

    func signOut() async {
        if let server, let current = tokens, let endpoints = try? await ServerClient.endpoints(server) {
            await ServerClient.revoke(current.refreshToken, endpoints: endpoints)
        }
        let host = server?.host
        server = nil
        open = false
        forgetTokens()
        Keychain.remove(Self.serverKey)
        await Self.clearWebData(host: host)
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
        let mine = records.filter { host != nil && $0.displayName.contains(host!) }
        await store.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), for: mine)
    }
}
