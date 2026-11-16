import CryptoKit
import Foundation

struct OfflineSnapshot: Equatable {
    let json: Data
    let version: Int
    let savedAt: Date
}

enum OfflineStoreError: Error, Equatable {
    case notATripSet
    case cannotWrite
}

final class OfflineStore: @unchecked Sendable {
    static let shared = OfflineStore()
    static let daysKeptAfterEnd = 3

    private static let tripsFile = "trips.json"
    private static let metaFile = "meta.json"
    private static let stagingPrefix = ".staging-"

    private struct Meta: Codable {
        let version: Int
        let savedAt: Date
    }

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return calendar
    }()

    private let root: URL
    private let now: () -> Date
    private let calendar: Calendar
    private let lock = NSLock()
    private let files = FileManager.default

    init(root: URL = OfflineStore.defaultRoot, calendar: Calendar = .current, now: @escaping () -> Date = Date.init) {
        self.root = root
        self.calendar = calendar
        self.now = now
    }

    static var defaultRoot: URL {
        URL.applicationSupportDirectory.appendingPathComponent("OfflineTrips", isDirectory: true)
    }

    func save(_ json: Data, version: Int, for server: URL) throws {
        guard Self.parse(json) != nil else { throw OfflineStoreError.notATripSet }
        guard let meta = try? JSONEncoder().encode(Meta(version: version, savedAt: now())) else { throw OfflineStoreError.cannotWrite }
        lock.lock()
        defer { lock.unlock() }
        try write(trips: json, meta: meta, to: folder(for: server))
    }

    func load(server: URL) -> OfflineSnapshot? {
        lock.lock()
        defer { lock.unlock() }
        let folder = folder(for: server)
        guard files.fileExists(atPath: folder.path) else { return nil }
        guard let stored = try? Data(contentsOf: folder.appendingPathComponent(Self.tripsFile)),
              let metaData = try? Data(contentsOf: folder.appendingPathComponent(Self.metaFile)),
              let meta = try? JSONDecoder().decode(Meta.self, from: metaData),
              let kept = prune(stored) else {
            try? files.removeItem(at: folder)
            return nil
        }
        if kept != stored {
            try? write(trips: kept, meta: metaData, to: folder)
        }
        return OfflineSnapshot(json: kept, version: meta.version, savedAt: meta.savedAt)
    }

    func savedAt(server: URL) -> Date? {
        load(server: server)?.savedAt
    }

    func tripNames(server: URL) -> [String] {
        guard let snapshot = load(server: server), let parsed = Self.parse(snapshot.json) else { return [] }
        return parsed.trips.compactMap { ($0["trip"] as? [String: Any])?["name"] as? String }
    }

    func purge(server: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        try remove(folder(for: server))
    }

    func purgeAll() throws {
        lock.lock()
        defer { lock.unlock() }
        try remove(root)
    }

    private func remove(_ url: URL) throws {
        guard files.fileExists(atPath: url.path) else { return }
        do {
            try files.removeItem(at: url)
        } catch {
            throw OfflineStoreError.cannotWrite
        }
    }

    private func folder(for server: URL) -> URL {
        var key = server.absoluteString.lowercased()
        while key.hasSuffix("/") { key.removeLast() }
        let name = SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
        return root.appendingPathComponent(name, isDirectory: true)
    }

    private func write(trips: Data, meta: Data, to folder: URL) throws {
        let protection: [FileAttributeKey: Any] = [.protectionKey: FileProtectionType.complete]
        let staging = root.appendingPathComponent(Self.stagingPrefix + UUID().uuidString, isDirectory: true)
        do {
            try files.createDirectory(at: root, withIntermediateDirectories: true, attributes: protection)
            discardLeftoverStaging()
            try files.createDirectory(at: staging, withIntermediateDirectories: false, attributes: protection)
            try trips.write(to: staging.appendingPathComponent(Self.tripsFile), options: .completeFileProtection)
            try meta.write(to: staging.appendingPathComponent(Self.metaFile), options: .completeFileProtection)
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

    private func discardLeftoverStaging() {
        let names = (try? files.contentsOfDirectory(atPath: root.path)) ?? []
        for name in names where name.hasPrefix(Self.stagingPrefix) {
            try? files.removeItem(at: root.appendingPathComponent(name))
        }
    }

    private static func parse(_ json: Data) -> (root: [String: Any], trips: [[String: Any]])? {
        guard let object = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
              let trips = object["trips"] as? [[String: Any]] else { return nil }
        return (object, trips)
    }

    private func prune(_ json: Data) -> Data? {
        guard var parsed = Self.parse(json) else { return nil }
        let today = calendar.dateComponents([.year, .month, .day], from: now())
        guard let todayDay = Self.utc.date(from: today) else { return json }
        let kept = parsed.trips.filter { !Self.hasExpired($0, today: todayDay) }
        if kept.count == parsed.trips.count { return json }
        parsed.root["trips"] = kept
        return try? JSONSerialization.data(withJSONObject: parsed.root, options: [.withoutEscapingSlashes])
    }

    private static func hasExpired(_ entry: [String: Any], today: Date) -> Bool {
        guard let trip = entry["trip"] as? [String: Any],
              let text = (trip["end_date"] as? String) ?? (trip["start_date"] as? String),
              let lastDay = day(text),
              let expiry = utc.date(byAdding: .day, value: daysKeptAfterEnd, to: lastDay) else { return false }
        return today > expiry
    }

    private static func day(_ text: String) -> Date? {
        let parts = text.prefix(10).split(separator: "-", omittingEmptySubsequences: false).map { Int($0) }
        guard parts.count == 3, let year = parts[0], let month = parts[1], let day = parts[2],
              let date = utc.date(from: DateComponents(year: year, month: month, day: day)) else { return nil }
        let back = utc.dateComponents([.year, .month, .day], from: date)
        return back.year == year && back.month == month && back.day == day ? date : nil
    }
}
