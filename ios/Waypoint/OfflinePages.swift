import CryptoKit
import Foundation
import UniformTypeIdentifiers

enum OfflinePageFiles {
    static let index = "/"
    static let shell = ["/logo.svg", "/fonts/Inter-latin-Variable.woff2", "/fonts/Inter-latin-ext-Variable.woff2",
                        "/fonts/Inter-Variable.woff2", "/fonts/GeistMono-Variable.woff2", "/manifest.webmanifest"]
    static let maxAssets = 300
    static let maxFileBytes = 10_000_000

    static func isAssetPath(_ path: String) -> Bool {
        guard path.hasPrefix("/assets/"), path.count <= 200, !path.contains("..") else { return false }
        return path.unicodeScalars.allSatisfy { scalar in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/".unicodeScalars.contains(scalar)
        }
    }

    static func assetPaths(in names: [String], origin server: URL) -> [String] {
        var paths = Set<String>()
        for name in names {
            guard let url = URL(string: name), Endpoints.origin(url) == Endpoints.origin(server), isAssetPath(url.path) else { continue }
            paths.insert(url.path)
        }
        return paths.sorted()
    }

    static func mimeType(for path: String) -> String {
        if path == index { return "text/html; charset=utf-8" }
        switch (path as NSString).pathExtension.lowercased() {
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "html": return "text/html; charset=utf-8"
        case "json": return "application/json"
        case "webmanifest": return "application/manifest+json"
        case "svg": return "image/svg+xml"
        case "woff2": return "font/woff2"
        case "woff": return "font/woff"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "webp": return "image/webp"
        default:
            let ext = (path as NSString).pathExtension
            return UTType(filenameExtension: ext)?.preferredMIMEType ?? "application/octet-stream"
        }
    }
}

final class OfflinePages: @unchecked Sendable {
    static let shared = OfflinePages()

    private static let metaFile = "meta.json"
    private static let stagingPrefix = ".staging-"

    private struct Meta: Codable {
        let build: String
        let savedAt: Date
        let paths: [String]
    }

    private let root: URL
    private let lock = NSLock()
    private let files = FileManager.default

    init(root: URL = OfflinePages.defaultRoot) {
        self.root = root
    }

    static var defaultRoot: URL {
        URL.applicationSupportDirectory.appendingPathComponent("OfflinePages", isDirectory: true)
    }

    func save(_ contents: [String: Data], build: String, for server: URL) throws {
        guard contents[OfflinePageFiles.index] != nil else { throw OfflineStoreError.notATripSet }
        let meta = Meta(build: build, savedAt: Date(), paths: contents.keys.sorted())
        guard let metaData = try? JSONEncoder().encode(meta) else { throw OfflineStoreError.cannotWrite }
        lock.lock()
        defer { lock.unlock() }
        let folder = folder(for: server)
        let protection: [FileAttributeKey: Any] = [.protectionKey: FileProtectionType.complete]
        let staging = root.appendingPathComponent(Self.stagingPrefix + UUID().uuidString, isDirectory: true)
        do {
            try files.createDirectory(at: root, withIntermediateDirectories: true, attributes: protection)
            discardLeftoverStaging()
            try files.createDirectory(at: staging, withIntermediateDirectories: false, attributes: protection)
            for (path, data) in contents {
                try data.write(to: staging.appendingPathComponent(Self.fileName(for: path)), options: .completeFileProtection)
            }
            try metaData.write(to: staging.appendingPathComponent(Self.metaFile), options: .completeFileProtection)
            if files.fileExists(atPath: folder.path) {
                _ = try files.replaceItemAt(folder, withItemAt: staging)
            } else {
                try files.moveItem(at: staging, to: folder)
            }
        } catch {
            try? files.removeItem(at: staging)
            throw OfflineStoreError.cannotWrite
        }
    }

    func build(for server: URL) -> String? {
        meta(for: server)?.build
    }

    func paths(for server: URL) -> [String] {
        meta(for: server)?.paths ?? []
    }

    func file(_ path: String, for server: URL) -> Data? {
        lock.lock()
        defer { lock.unlock() }
        guard let meta = readMeta(folder(for: server)), meta.paths.contains(path) else { return nil }
        return try? Data(contentsOf: folder(for: server).appendingPathComponent(Self.fileName(for: path)))
    }

    func hasPage(for server: URL) -> Bool {
        file(OfflinePageFiles.index, for: server) != nil
    }

    func purge(server: URL) {
        lock.lock()
        defer { lock.unlock() }
        try? files.removeItem(at: folder(for: server))
    }

    func purgeAll() throws {
        lock.lock()
        defer { lock.unlock() }
        guard files.fileExists(atPath: root.path) else { return }
        do {
            try files.removeItem(at: root)
        } catch {
            throw OfflineStoreError.cannotWrite
        }
    }

    private func meta(for server: URL) -> Meta? {
        lock.lock()
        defer { lock.unlock() }
        return readMeta(folder(for: server))
    }

    private func readMeta(_ folder: URL) -> Meta? {
        guard let data = try? Data(contentsOf: folder.appendingPathComponent(Self.metaFile)) else { return nil }
        return try? JSONDecoder().decode(Meta.self, from: data)
    }

    private func folder(for server: URL) -> URL {
        root.appendingPathComponent(OfflineStore.folderName(for: server), isDirectory: true)
    }

    private static func fileName(for path: String) -> String {
        "f-" + SHA256.hash(data: Data(path.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func discardLeftoverStaging() {
        let names = (try? files.contentsOfDirectory(atPath: root.path)) ?? []
        for name in names where name.hasPrefix(Self.stagingPrefix) {
            try? files.removeItem(at: root.appendingPathComponent(name))
        }
    }
}
