import Foundation
import Security

/// A Keychain read is not only found or missing: before the first unlock after a restart the items cannot be read at all, and that is not
/// "signed out".
enum KeychainRead: Equatable {
    case found(Data)
    case missing
    case unavailable
}

protocol KeychainReading: Sendable {
    func read(_ key: String) -> KeychainRead
}

struct LiveKeychainReader: KeychainReading {
    func read(_ key: String) -> KeychainRead { Keychain.read(key) }
}

enum Keychain {
    private static let service = "com.anthonypluth.waypoint"

    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: key]
    }

    static func set(_ value: Data, for key: String) {
        SecItemDelete(query(key) as CFDictionary)
        var add = query(key)
        add[kSecValueData as String] = value
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    static func read(_ key: String) -> KeychainRead {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        if status == errSecItemNotFound { return .missing }
        guard status == errSecSuccess, let data = out as? Data else { return .unavailable }
        return .found(data)
    }

    static func get(_ key: String) -> Data? {
        if case .found(let data) = read(key) { return data }
        return nil
    }

    static func remove(_ key: String) {
        SecItemDelete(query(key) as CFDictionary)
    }
}
