import AuthenticationServices
import UIKit

@MainActor
final class SignIn: NSObject, ASWebAuthenticationPresentationContextProviding {
    private var session: ASWebAuthenticationSession?

    func run(endpoints: Endpoints) async throws -> Tokens {
        let verifier = PKCE.random()
        let state = PKCE.random()
        guard var parts = URLComponents(url: endpoints.authorizationEndpoint, resolvingAgainstBaseURL: false) else {
            throw ServerError.notWaypoint
        }
        parts.queryItems = [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: AppClient.clientID),
            URLQueryItem(name: "redirect_uri", value: AppClient.redirectURI),
            URLQueryItem(name: "scope", value: AppClient.scope),
            URLQueryItem(name: "resource", value: endpoints.resource),
            URLQueryItem(name: "state", value: state),
            URLQueryItem(name: "code_challenge", value: PKCE.challenge(for: verifier)),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
        ]
        guard let start = parts.url else { throw ServerError.notWaypoint }
        let callback = try await open(start)
        let code = try SignIn.code(from: callback, state: state, issuer: endpoints.issuer)
        return try await ServerClient.exchange(code: code, verifier: verifier, endpoints: endpoints)
    }

    nonisolated static func code(from callback: URL, state: String, issuer: String) throws -> String {
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { items.first { $0.name == name }?.value }
        if let error = value("error") {
            throw ServerError.signInFailed(value("error_description") ?? error)
        }
        guard value("state") == state else { throw ServerError.signInFailed("the reply didn't match this sign-in") }
        if let iss = value("iss"), iss != issuer { throw ServerError.signInFailed("the reply came from a different server") }
        guard let code = value("code"), !code.isEmpty else { throw ServerError.signInFailed("the reply had no code") }
        return code
    }

    private func open(_ url: URL) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: AppClient.callbackScheme) { callback, error in
                if let callback {
                    continuation.resume(returning: callback)
                } else if let error = error as? ASWebAuthenticationSessionError, error.code == .canceledLogin {
                    continuation.resume(throwing: ServerError.signInFailed("you closed the sign-in"))
                } else {
                    continuation.resume(throwing: ServerError.signInFailed(error?.localizedDescription ?? "unknown error"))
                }
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false
            self.session = session
            if !session.start() {
                continuation.resume(throwing: ServerError.signInFailed("the sign-in sheet couldn't open"))
            }
        }
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        return scene?.keyWindow ?? ASPresentationAnchor()
    }
}
