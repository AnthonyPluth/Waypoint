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
    private static let placesFile = "arrival-places.json"
    private static let arrivalFile = "arrival-watch.json"
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
        if isLocked(folder) { return nil }
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

    /// Whether the saved copy exists but iOS will not let it be read now (the phone is locked, so a background launch for a region sees
    /// this). A copy in that state is kept: `load` answers nil for it without deleting anything.
    func isLocked(server: URL) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return isLocked(folder(for: server))
    }

    private func isLocked(_ folder: URL) -> Bool {
        let file = folder.appendingPathComponent(Self.tripsFile)
        guard files.fileExists(atPath: file.path) else { return false }
        do {
            _ = try Data(contentsOf: file)
            return false
        } catch {
            return Self.refusesToRead(error as NSError)
        }
    }

    private static func refusesToRead(_ error: NSError) -> Bool {
        if error.domain == NSCocoaErrorDomain, error.code == NSFileReadNoPermissionError { return true }
        let underneath = error.userInfo[NSUnderlyingErrorKey] as? NSError
        let refused = [Int(EPERM), Int(EACCES)]
        if error.domain == NSPOSIXErrorDomain { return refused.contains(error.code) }
        if let underneath, underneath.domain == NSPOSIXErrorDomain { return refused.contains(underneath.code) }
        return false
    }

    func savedAt(server: URL) -> Date? {
        load(server: server)?.savedAt
    }

    func tripNames(server: URL) -> [String] {
        guard let snapshot = load(server: server), let parsed = Self.parse(snapshot.json) else { return [] }
        return parsed.trips.compactMap { ($0["trip"] as? [String: Any])?["name"] as? String }
    }

    /// The arrival places file (`ArrivalPlaces`) lives in the server's folder beside the saved trips, so every purge and every expiry takes it
    /// with them. It is never written without a saved copy, and a save of the trips carries it over (the lookups it caches are kept).
    func savePlaces(_ data: Data, for server: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        let folder = folder(for: server)
        guard files.fileExists(atPath: folder.path) else { return }
        do {
            try data.write(to: folder.appendingPathComponent(Self.placesFile), options: [.atomic, .completeFileProtection])
        } catch {
            throw OfflineStoreError.cannotWrite
        }
    }

    func loadPlaces(server: URL) -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return try? Data(contentsOf: folder(for: server).appendingPathComponent(Self.placesFile))
    }

    func deletePlaces(server: URL) {
        lock.lock()
        defer { lock.unlock() }
        try? files.removeItem(at: folder(for: server).appendingPathComponent(Self.placesFile))
    }

    /// The arrival file (`ArrivalWatch`): the places being watched, for a wake-up while the phone is locked, so it is the one file here that
    /// iOS can read after the first unlock. It lives in the server's folder, carries through each save and goes with every purge. Never
    /// written without a saved copy, and read without touching the saved trips.
    func saveArrival(_ data: Data, for server: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        let folder = folder(for: server)
        guard files.fileExists(atPath: folder.path) else { return }
        do {
            let file = folder.appendingPathComponent(Self.arrivalFile)
            try data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            Self.excludeFromBackup(file)
        } catch {
            throw OfflineStoreError.cannotWrite
        }
    }

    func loadArrival(server: URL) -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return try? Data(contentsOf: folder(for: server).appendingPathComponent(Self.arrivalFile))
    }

    func deleteArrival(server: URL) {
        lock.lock()
        defer { lock.unlock() }
        try? files.removeItem(at: folder(for: server).appendingPathComponent(Self.arrivalFile))
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

    static func folderName(for server: URL) -> String {
        var key = server.absoluteString.lowercased()
        while key.hasSuffix("/") { key.removeLast() }
        return SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func folder(for server: URL) -> URL {
        root.appendingPathComponent(Self.folderName(for: server), isDirectory: true)
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
            if let earlier = try? Data(contentsOf: folder.appendingPathComponent(Self.placesFile)),
               let carried = Self.placesKept(earlier, trips: trips) {
                try carried.write(to: staging.appendingPathComponent(Self.placesFile), options: .completeFileProtection)
            }
            if let earlier = try? Data(contentsOf: folder.appendingPathComponent(Self.arrivalFile)),
               let carried = Self.arrivalKept(earlier, trips: trips) {
                let file = staging.appendingPathComponent(Self.arrivalFile)
                try carried.write(to: file, options: .completeFileProtectionUntilFirstUserAuthentication)
                Self.excludeFromBackup(file)
            }
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

    /// The arrival places file as it stays when the saved trips become `trips` (a save, or an expiry on load): only the places of a trip still
    /// saved, and only the cached lookups some such trip uses. Nothing left means no file (nil), so expired trips leave no coordinates behind.
    private static func placesKept(_ places: Data, trips: Data) -> Data? {
        guard let saved = parse(trips),
              var object = try? JSONSerialization.jsonObject(with: places) as? [String: Any],
              let listed = object["places"] as? [[String: Any]] else { return nil }
        let ids = Set(saved.trips.compactMap { ($0["trip"] as? [String: Any])?["id"] as? Int })
        let keptPlaces = listed.filter { ids.contains($0["tripId"] as? Int ?? -1) }
        guard !keptPlaces.isEmpty else { return nil }
        var keptLookups: [String: Any] = [:]
        for (key, value) in object["geocoded"] as? [String: [String: Any]] ?? [:] {
            let users = (value["tripIds"] as? [Int] ?? []).filter { ids.contains($0) }
            if users.isEmpty { continue }
            var lookup = value
            lookup["tripIds"] = users
            keptLookups[key] = lookup
        }
        object["places"] = keptPlaces
        object["geocoded"] = keptLookups
        return try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    /// The arrival file as it stays when the saved trips become `trips`: only the watched places of a trip still saved, none meaning no file.
    private static func arrivalKept(_ arrival: Data, trips: Data) -> Data? {
        guard let saved = parse(trips),
              var object = try? JSONSerialization.jsonObject(with: arrival) as? [String: Any],
              let listed = object["watched"] as? [[String: Any]] else { return nil }
        let ids = Set(saved.trips.compactMap { ($0["trip"] as? [String: Any])?["id"] as? Int })
        let kept = listed.filter { ids.contains(($0["place"] as? [String: Any])?["tripId"] as? Int ?? -1) }
        guard !kept.isEmpty else { return nil }
        object["watched"] = kept
        return try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    private static func excludeFromBackup(_ file: URL) {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var target = file
        try? target.setResourceValues(values)
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
