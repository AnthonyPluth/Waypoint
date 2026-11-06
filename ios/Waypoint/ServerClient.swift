import Foundation

enum AppClient {
    static let clientID = "wpc_waypoint_ios"
    static let redirectURI = "waypoint://auth"
    static let callbackScheme = "waypoint"
    static let scope = "app"
}

struct Tokens: Codable, Equatable {
    var accessToken: String
    var refreshToken: String
    var expiresAt: Date
}

struct Endpoints: Decodable {
    let issuer: String
    let authorizationEndpoint: URL
    let tokenEndpoint: URL
    let revocationEndpoint: URL?

    enum CodingKeys: String, CodingKey {
        case issuer
        case authorizationEndpoint = "authorization_endpoint"
        case tokenEndpoint = "token_endpoint"
        case revocationEndpoint = "revocation_endpoint"
    }

    var resource: String { issuer + "/app" }
}

enum ServerError: LocalizedError {
    case badAddress
    case notReachable(String)
    case notWaypoint
    case needsPublicURL
    case signInFailed(String)
    case signedOut

    var errorDescription: String? {
        switch self {
        case .badAddress:
            return "That doesn't look like a web address. Try something like https://waypoint.example.com."
        case .notReachable(let why):
            return "Couldn't reach that address: \(why)"
        case .notWaypoint:
            return "That address answered, but it doesn't look like Waypoint."
        case .needsPublicURL:
            return "This Waypoint can't sign in apps yet. Set WAYPOINT_PUBLIC_URL on the server."
        case .signInFailed(let why):
            return "Sign-in didn't finish: \(why)"
        case .signedOut:
            return "You've been signed out of Waypoint. Sign in again."
        }
    }
}

private struct TokenReply: Decodable {
    let accessToken: String
    let refreshToken: String
    let expiresIn: Double

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case expiresIn = "expires_in"
    }
}

private struct OAuthFailure: Decodable {
    let error: String
    let errorDescription: String?

    enum CodingKeys: String, CodingKey {
        case error
        case errorDescription = "error_description"
    }
}

struct WebCookie: Decodable {
    let name: String
    let value: String
    let maxAge: Int
    let secure: Bool

    enum CodingKeys: String, CodingKey {
        case name, value, secure
        case maxAge = "max_age"
    }
}

enum ServerClient {
    static func normalize(_ text: String) throws -> URL {
        var t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { throw ServerError.badAddress }
        if !t.contains("://") { t = "https://" + t }
        while t.hasSuffix("/") { t.removeLast() }
        guard let url = URL(string: t), let scheme = url.scheme, ["https", "http"].contains(scheme),
              let host = url.host, !host.isEmpty, url.user == nil else { throw ServerError.badAddress }
        return url
    }

    static func get(_ url: URL, bearer: String? = nil) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.setValue("1", forHTTPHeaderField: "X-Waypoint")
        if let bearer { request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization") }
        return try await send(request)
    }

    static func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw ServerError.notWaypoint }
            return (data, http)
        } catch let error as ServerError {
            throw error
        } catch {
            throw ServerError.notReachable(error.localizedDescription)
        }
    }

    static func opensWithoutSignIn(_ server: URL) async throws -> Bool {
        let (data, response) = try await get(server.appendingPathComponent("api/trips"))
        guard response.statusCode == 200 else { return false }
        let json = try? JSONSerialization.jsonObject(with: data)
        return json is [Any] || json is [String: Any]
    }

    static func endpoints(_ server: URL) async throws -> Endpoints {
        let (data, response) = try await get(server.appendingPathComponent(".well-known/oauth-authorization-server"))
        if response.statusCode == 404 { throw ServerError.needsPublicURL }
        guard response.statusCode == 200, let found = try? JSONDecoder().decode(Endpoints.self, from: data) else {
            throw ServerError.notWaypoint
        }
        return found
    }

    static func form(_ url: URL, _ fields: [String: String]) -> URLRequest {
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        var parts = URLComponents()
        parts.queryItems = fields.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        request.httpBody = parts.percentEncodedQuery?.data(using: .utf8)
        return request
    }

    static func exchange(code: String, verifier: String, endpoints: Endpoints, now: Date = Date()) async throws -> Tokens {
        try await tokens(from: form(endpoints.tokenEndpoint, [
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "redirect_uri": AppClient.redirectURI, "client_id": AppClient.clientID, "resource": endpoints.resource,
        ]), now: now)
    }

    static func refresh(_ refreshToken: String, endpoints: Endpoints, now: Date = Date()) async throws -> Tokens {
        try await tokens(from: form(endpoints.tokenEndpoint, [
            "grant_type": "refresh_token", "refresh_token": refreshToken,
            "client_id": AppClient.clientID, "resource": endpoints.resource,
        ]), now: now)
    }

    private static func tokens(from request: URLRequest, now: Date) async throws -> Tokens {
        let (data, response) = try await send(request)
        guard response.statusCode == 200, let reply = try? JSONDecoder().decode(TokenReply.self, from: data) else {
            let why = (try? JSONDecoder().decode(OAuthFailure.self, from: data))
            if why?.error == "invalid_grant" { throw ServerError.signedOut }
            throw ServerError.signInFailed(why?.errorDescription ?? "the server said \(response.statusCode)")
        }
        return Tokens(accessToken: reply.accessToken, refreshToken: reply.refreshToken,
                      expiresAt: now.addingTimeInterval(reply.expiresIn))
    }

    static func webCookie(_ server: URL, accessToken: String) async throws -> WebCookie {
        var request = URLRequest(url: server.appendingPathComponent("auth/app-session"), timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("1", forHTTPHeaderField: "X-Waypoint")
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await send(request)
        if response.statusCode == 401 { throw ServerError.signedOut }
        guard response.statusCode == 200, let cookie = try? JSONDecoder().decode(WebCookie.self, from: data) else {
            throw ServerError.notWaypoint
        }
        return cookie
    }

    static func revoke(_ refreshToken: String, endpoints: Endpoints) async {
        guard let url = endpoints.revocationEndpoint else { return }
        _ = try? await send(form(url, ["token": refreshToken, "client_id": AppClient.clientID]))
    }
}
