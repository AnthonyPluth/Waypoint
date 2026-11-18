import XCTest
@testable import Waypoint

private final class TestClock {
    var date: Date
    init(_ date: Date) { self.date = date }
}

final class OfflineStoreTests: XCTestCase {
    private var root: URL!
    private var clock: TestClock!
    private var store: OfflineStore!
    private let home = URL(string: "https://waypoint.example.com")!
    private let cabin = URL(string: "http://192.168.1.20:8080")!

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    private static func noon(_ year: Int, _ month: Int, _ day: Int) -> Date {
        utc.date(from: DateComponents(year: year, month: month, day: day, hour: 12))!
    }

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("offline-store-\(UUID().uuidString)", isDirectory: true)
        clock = TestClock(Self.noon(2026, 11, 10))
        store = makeStore()
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        super.tearDown()
    }

    private func makeStore() -> OfflineStore {
        OfflineStore(root: root, calendar: Self.utc, now: { [clock] in clock!.date })
    }

    private func reply(_ trips: [(name: String, start: String?, end: String?)], version: Int = 1) -> Data {
        let entries: [[String: Any]] = trips.enumerated().map { index, trip in
            ["trip": ["id": index + 1, "name": trip.name,
                      "start_date": trip.start.map { $0 as Any } ?? NSNull(), "end_date": trip.end.map { $0 as Any } ?? NSNull()] as [String: Any],
             "messages": [] as [Any]]
        }
        return try! JSONSerialization.data(withJSONObject: ["version": version, "trips": entries])
    }

    private func names(_ server: URL) -> [String] {
        store.tripNames(server: server)
    }

    private func files(under url: URL) -> [URL] {
        let walker = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.isRegularFileKey])
        return (walker?.allObjects as? [URL] ?? []).filter { (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
    }

    func testNothingIsSavedAtFirst() {
        XCTAssertNil(store.load(server: home))
        XCTAssertNil(store.savedAt(server: home))
        XCTAssertEqual(names(home), [])
    }

    func testSaveThenLoadGivesBackTheReplyItsVersionAndTheSavedAtDate() throws {
        let data = reply([("Alpine week", "2026-11-12", "2026-11-19")], version: 3)
        try store.save(data, version: 3, for: home)
        let loaded = try XCTUnwrap(store.load(server: home))
        XCTAssertEqual(loaded.json, data)
        XCTAssertEqual(loaded.version, 3)
        XCTAssertEqual(loaded.savedAt, clock.date)
        XCTAssertEqual(store.savedAt(server: home), clock.date)
        XCTAssertEqual(names(home), ["Alpine week"])
    }

    func testTheSavedCopyIsStillThereForANewStoreOverTheSameFolder() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        XCTAssertEqual(makeStore().tripNames(server: home), ["Alpine week"])
    }

    func testASecondSaveReplacesTheFirstInsteadOfMergingWithIt() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19"), ("Beach days", "2026-11-20", "2026-11-25")], version: 1), version: 1, for: home)
        clock.date = Self.noon(2026, 11, 11)
        let second = reply([("City break", "2026-11-14", "2026-11-16")], version: 2)
        try store.save(second, version: 2, for: home)
        let loaded = try XCTUnwrap(store.load(server: home))
        XCTAssertEqual(loaded.json, second)
        XCTAssertEqual(loaded.version, 2)
        XCTAssertEqual(loaded.savedAt, clock.date)
        XCTAssertEqual(names(home), ["City break"])
    }

    func testASaveWithNoTripsReplacesEverythingWithAnEmptySet() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        try store.save(reply([]), version: 1, for: home)
        XCTAssertNotNil(store.load(server: home))
        XCTAssertEqual(names(home), [])
    }

    func testAReplyThatIsNotATripSetIsRefusedAndKeepsWhatWasSaved() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        for bad in ["not json", "[]", "{}", "{\"trips\": 5}", "{\"trips\": [1]}"] {
            XCTAssertThrowsError(try store.save(Data(bad.utf8), version: 2, for: home), bad) {
                XCTAssertEqual($0 as? OfflineStoreError, .notATripSet)
            }
        }
        XCTAssertEqual(names(home), ["Alpine week"])
    }

    func testEachServerKeepsItsOwnTrips() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        try store.save(reply([("Cabin weekend", "2026-11-13", "2026-11-15")]), version: 2, for: cabin)
        XCTAssertEqual(names(home), ["Alpine week"])
        XCTAssertEqual(names(cabin), ["Cabin weekend"])
        XCTAssertEqual(store.load(server: home)?.version, 1)
        XCTAssertEqual(store.load(server: cabin)?.version, 2)
        XCTAssertNil(store.load(server: URL(string: "https://other.example.com")!))
    }

    func testTheSameAddressWrittenDifferentlyIsTheSameServer() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        XCTAssertEqual(names(URL(string: "https://Waypoint.Example.com/")!), ["Alpine week"])
    }

    func testATripIsKeptThroughTheThirdDayAfterItEndsAndDroppedAfter() throws {
        try store.save(reply([("Ended trip", "2026-11-01", "2026-11-10"), ("Later trip", "2026-11-20", "2026-11-25")]), version: 1, for: home)
        clock.date = Self.noon(2026, 11, 13)
        XCTAssertEqual(names(home), ["Ended trip", "Later trip"])
        clock.date = Self.noon(2026, 11, 14)
        XCTAssertEqual(names(home), ["Later trip"])
    }

    func testAnExpiredTripIsRemovedFromTheFilesAndStaysGone() throws {
        try store.save(reply([("Ended trip", "2026-11-01", "2026-11-10"), ("Later trip", "2026-11-20", "2026-11-25")], version: 4), version: 4, for: home)
        clock.date = Self.noon(2026, 11, 14)
        let loaded = try XCTUnwrap(store.load(server: home))
        XCTAssertEqual(loaded.version, 4)
        XCTAssertEqual(loaded.savedAt, Self.noon(2026, 11, 10))
        clock.date = Self.noon(2026, 11, 10)
        XCTAssertEqual(names(home), ["Later trip"])
        let onDisk = try files(under: root).map { try String(contentsOf: $0, encoding: .utf8) }.joined()
        XCTAssertFalse(onDisk.contains("Ended trip"))
    }

    func testACarriedCitiesMapSurvivesSaveLoadAndPruning() throws {
        let cities = ["DEN": "Denver", "GJT": "Grand Junction"]
        let entries: [[String: Any]] = [("Ended trip", "2026-11-01", "2026-11-10", ["LIS": "Lisbon"]), ("Later trip", "2026-11-20", "2026-11-25", cities)].enumerated().map { index, trip in
            ["trip": ["id": index + 1, "name": trip.0, "start_date": trip.1, "end_date": trip.2] as [String: Any], "messages": [] as [Any], "cities": trip.3]
        }
        let data = try JSONSerialization.data(withJSONObject: ["version": 1, "trips": entries])
        try store.save(data, version: 1, for: home)
        XCTAssertEqual(try XCTUnwrap(store.load(server: home)).json, data)
        clock.date = Self.noon(2026, 11, 14)
        let loaded = try XCTUnwrap(store.load(server: home))
        let decoded = try XCTUnwrap(try JSONSerialization.jsonObject(with: loaded.json) as? [String: Any])
        let kept = try XCTUnwrap(decoded["trips"] as? [[String: Any]])
        XCTAssertEqual(kept.count, 1)
        XCTAssertEqual(kept.first?["cities"] as? [String: String], cities)
    }

    func testEveryTripExpiredLeavesAnEmptySetRatherThanNothing() throws {
        try store.save(reply([("Ended trip", "2026-11-01", "2026-11-05")]), version: 1, for: home)
        clock.date = Self.noon(2026, 12, 1)
        XCTAssertNotNil(store.load(server: home))
        XCTAssertEqual(names(home), [])
    }

    func testATripWithOnlyAStartDateExpiresFromThatDayAndOneWithNoDatesIsKept() throws {
        try store.save(reply([("Start only", "2026-11-01", nil), ("Undated", nil, nil)]), version: 1, for: home)
        XCTAssertEqual(names(home), ["Undated"])
    }

    func testPurgeOfOneServerLeavesTheOthers() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        try store.save(reply([("Cabin weekend", "2026-11-13", "2026-11-15")]), version: 1, for: cabin)
        try store.purge(server: home)
        XCTAssertNil(store.load(server: home))
        XCTAssertEqual(names(cabin), ["Cabin weekend"])
    }

    func testPurgeAllRemovesEveryServersTripsFromDisk() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        try store.save(reply([("Cabin weekend", "2026-11-13", "2026-11-15")]), version: 1, for: cabin)
        try store.purgeAll()
        XCTAssertNil(store.load(server: home))
        XCTAssertNil(store.load(server: cabin))
        XCTAssertTrue(files(under: root).isEmpty)
    }

    func testPurgingWhenNothingIsSavedIsFine() throws {
        try store.purge(server: home)
        try store.purgeAll()
    }

    func testSavingAfterAPurgeWorks() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        try store.purgeAll()
        try store.save(reply([("City break", "2026-11-14", "2026-11-16")]), version: 1, for: home)
        XCTAssertEqual(names(home), ["City break"])
    }

    func testNoTemporaryFilesAreLeftAfterASave() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        try store.save(reply([("City break", "2026-11-14", "2026-11-16")]), version: 2, for: home)
        let top = try FileManager.default.contentsOfDirectory(atPath: root.path)
        XCTAssertEqual(top.count, 1)
        XCTAssertFalse(top.contains { $0.hasPrefix(".staging-") })
        XCTAssertEqual(files(under: root).count, 2)
    }

    func testACorruptSavedCopyIsDeletedAndReadsAsNothing() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        let saved = files(under: root).first { $0.lastPathComponent == "trips.json" }!
        try Data("garbage".utf8).write(to: saved)
        XCTAssertNil(store.load(server: home))
        XCTAssertTrue(files(under: root).isEmpty)
    }

    func testSavedFilesCarryCompleteFileProtection() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        let saved = files(under: root)
        XCTAssertEqual(saved.count, 2)
        for file in saved {
            let value = try FileManager.default.attributesOfItem(atPath: file.path)[.protectionKey] as? FileProtectionType
            #if targetEnvironment(simulator)
            if let value { XCTAssertEqual(value, .complete, file.lastPathComponent) }
            #else
            XCTAssertEqual(value, .complete, file.lastPathComponent)
            #endif
        }
    }

    func testTheSavedFolderIsNotExcludedFromBackups() throws {
        try store.save(reply([("Alpine week", "2026-11-12", "2026-11-19")]), version: 1, for: home)
        for file in files(under: root) {
            XCTAssertNotEqual(try file.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)
        }
    }

    func testTheDefaultFolderIsInApplicationSupport() {
        XCTAssertTrue(OfflineStore.defaultRoot.path.contains("Application Support"))
    }
}
