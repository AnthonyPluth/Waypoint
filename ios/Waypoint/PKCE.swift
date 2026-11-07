import CryptoKit
import Foundation
import Security

enum PKCE {
    static func random() throws -> String {
        try random { count, buffer in SecRandomCopyBytes(kSecRandomDefault, count, buffer) }
    }

    static func random(fill: (Int, UnsafeMutableRawPointer) -> Int32) throws -> String {
        var bytes = [UInt8](repeating: 0, count: 48)
        guard fill(bytes.count, &bytes) == errSecSuccess else {
            throw ServerError.signInFailed("this device couldn't make a secure random value")
        }
        return base64URL(Data(bytes))
    }

    static func challenge(for verifier: String) -> String {
        base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
    }

    static func base64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
