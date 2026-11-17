import WebKit
import XCTest
@testable import Waypoint

enum TripFixtures {
    static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    static let now = utc.date(from: DateComponents(year: 2026, month: 11, day: 10, hour: 12))!

    static func store(at root: URL, now: Date = TripFixtures.now) -> OfflineStore {
        OfflineStore(root: root, calendar: utc, now: { now })
    }

    static func reply(_ names: [String], version: Int = 1, end: String = "2026-12-08") -> Data {
        let entries: [[String: Any]] = names.enumerated().map { index, name in
            ["trip": ["id": index + 1, "name": name, "start_date": "2026-12-01", "end_date": end] as [String: Any],
             "messages": [["id": 7, "subject": "Booking \(name)"] as [String: Any]]]
        }
        return try! JSONSerialization.data(withJSONObject: ["version": version, "trips": entries])
    }
}

final class OfflineBridgeTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!
    private var suite: String!
    private var store: OfflineStore!
    private var pages: OfflinePages!
    private var settings: OfflineSettings!
    private var sync: OfflineSync!
    private var bridge: OfflineBridge!
    private let home = URL(string: "https://waypoint.example.com")!

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("offline-bridge-\(UUID().uuidString)", isDirectory: true)
        suite = "offline-bridge-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        store = TripFixtures.store(at: root.appendingPathComponent("trips"))
        pages = OfflinePages(root: root.appendingPathComponent("pages"))
        settings = OfflineSettings(defaults: defaults)
        sync = OfflineSync(store: store, settings: settings, pages: pages, server: { [home] in home }, bearer: { nil })
        bridge = OfflineBridge(store: store, sync: sync, settings: settings)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private func ask(_ body: Any) async throws -> [String: Any] {
        try await bridge.answer(body, server: home)
    }

    private func trips(_ reply: [String: Any]) -> [[String: Any]] {
        reply["trips"] as? [[String: Any]] ?? []
    }

    func testStatusWithNothingSaved() async throws {
        let reply = try await ask(["type": "status"])
        XCTAssertEqual(reply["version"] as? Int, 1)
        XCTAssertEqual(reply["saving"] as? Bool, true)
        XCTAssertEqual(reply["syncing"] as? Bool, false)
        XCTAssertEqual(reply["lastSaveFailed"] as? Bool, false)
        XCTAssertTrue(reply["savedAt"] is NSNull)
        XCTAssertTrue(trips(reply).isEmpty)
    }

    func testStatusReportsSavingOffAfterItIsSwitchedOff() async throws {
        let reply = try await ask(["type": "setSaving", "on": false])
        XCTAssertEqual(reply["saving"] as? Bool, false)
    }

    func testStatusReportsASyncInProgressAndAFailedSave() async throws {
        sync.state.began()
        sync.state.setFailed(true)
        let reply = try await ask(["type": "status"])
        XCTAssertEqual(reply["syncing"] as? Bool, true)
        XCTAssertEqual(reply["lastSaveFailed"] as? Bool, true)
        sync.state.ended()
        let after = try await ask(["type": "status"])
        XCTAssertEqual(after["syncing"] as? Bool, false)
    }

    func testStatusListsTheSavedTripsInOrderWithTheSavedAtDate() async throws {
        try store.save(TripFixtures.reply(["Lisbon", "Oslo"]), version: 1, for: home)
        settings.set(true)
        let reply = try await ask(["type": "status"])
        XCTAssertEqual(reply["saving"] as? Bool, true)
        let saved = try XCTUnwrap(store.load(server: home)?.savedAt)
        XCTAssertEqual(reply["savedAt"] as? Int, Int((saved.timeIntervalSince1970 * 1000).rounded()))
        let listed = trips(reply)
        XCTAssertEqual(listed.map { $0["id"] as? Int }, [1, 2])
        XCTAssertEqual(listed.map { $0["name"] as? String }, ["Lisbon", "Oslo"])
        XCTAssertEqual(listed.map { Set($0.keys) }, [["id", "name"], ["id", "name"]])
    }

    func testAnUnknownVersionOnDiskReadsAsNothingSaved() async throws {
        try store.save(TripFixtures.reply(["Lisbon"], version: 2), version: 2, for: home)
        let status = try await ask(["type": "status"])
        XCTAssertTrue(status["savedAt"] is NSNull)
        let loaded = try await ask(["type": "load"])
        XCTAssertTrue(trips(loaded).isEmpty)
    }

    func testLoadReturnsEachSavedTripAsSavedPlusTheSavedAtDate() async throws {
        try store.save(TripFixtures.reply(["Lisbon", "Oslo"]), version: 1, for: home)
        let reply = try await ask(["type": "load"])
        XCTAssertEqual(reply["version"] as? Int, 1)
        let saved = try XCTUnwrap(store.load(server: home))
        let stored = try XCTUnwrap(try JSONSerialization.jsonObject(with: saved.json) as? [String: Any])
        let storedTrips = try XCTUnwrap(stored["trips"] as? [[String: Any]])
        let loaded = trips(reply)
        XCTAssertEqual(loaded.count, 2)
        let millis = Int((saved.savedAt.timeIntervalSince1970 * 1000).rounded())
        for (index, entry) in loaded.enumerated() {
            XCTAssertEqual(entry["savedAt"] as? Int, millis)
            var rest = entry
            rest.removeValue(forKey: "savedAt")
            XCTAssertEqual(NSDictionary(dictionary: rest), NSDictionary(dictionary: storedTrips[index]))
        }
    }

    func testLoadWithNothingSavedIsEmpty() async throws {
        let reply = try await ask(["type": "load"])
        XCTAssertEqual(reply["version"] as? Int, 1)
        XCTAssertTrue(trips(reply).isEmpty)
    }

    func testLoadDropsTripsThatEndedMoreThanThreeDaysAgo() async throws {
        try store.save(TripFixtures.reply(["Lisbon"], end: "2026-11-05"), version: 1, for: home)
        let later = TripFixtures.store(at: root.appendingPathComponent("trips"), now: TripFixtures.utc.date(from: DateComponents(year: 2026, month: 11, day: 9, hour: 12))!)
        let sync = OfflineSync(store: later, settings: settings, pages: pages, server: { [home] in home }, bearer: { nil })
        let answered = try await OfflineBridge(store: later, sync: sync, settings: settings).answer(["type": "load"], server: home)
        XCTAssertTrue(trips(answered).isEmpty)
    }

    func testRepliesAreWhatWebKitCanPassToThePage() async throws {
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: home)
        for body in [["type": "status"], ["type": "load"]] {
            let reply = try await ask(body)
            XCTAssertTrue(JSONSerialization.isValidJSONObject(reply), "\(body)")
        }
    }

    func testSettingSavingOnOnlyTurnsTheFlagOn() async throws {
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: home)
        let reply = try await ask(["type": "setSaving", "on": true])
        XCTAssertEqual(reply["saving"] as? Bool, true)
        XCTAssertTrue(settings.isOn)
        XCTAssertEqual(trips(reply).count, 1)
        XCTAssertEqual(store.tripNames(server: home), ["Lisbon"])
    }

    func testSettingSavingOffPurgesTheSavedTripsAndThePages() async throws {
        settings.set(true)
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: home)
        try pages.save(["/": Data("<html/>".utf8)], build: "b", for: home)
        let reply = try await ask(["type": "setSaving", "on": false])
        XCTAssertEqual(reply["saving"] as? Bool, false)
        XCTAssertTrue(reply["savedAt"] is NSNull)
        XCTAssertTrue(trips(reply).isEmpty)
        XCTAssertFalse(settings.isOn)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testRemovePurgesTheCopyAndLeavesTheFlagAlone() async throws {
        settings.set(true)
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: home)
        try pages.save(["/": Data("<html/>".utf8)], build: "b", for: home)
        let reply = try await ask(["type": "remove"])
        XCTAssertEqual(reply["saving"] as? Bool, true)
        XCTAssertTrue(reply["savedAt"] is NSNull)
        XCTAssertTrue(trips(reply).isEmpty)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testARequestTheHandlerDoesNotKnowFails() async {
        let bodies: [Any] = [["type": "delete"], ["type": 3], ["nothing": true], "status", 7, ["type": "setSaving"], ["type": "setSaving", "on": "yes"]]
        for body in bodies {
            do {
                _ = try await ask(body)
                XCTFail("\(body) should have been refused")
            } catch {
                XCTAssertEqual(error as? OfflineBridge.Failure, .unknownRequest)
            }
        }
        XCTAssertTrue(settings.isOn)
    }

    func testTheServersOwnPageIsTrusted() {
        XCTAssertTrue(BridgeOrigin.accepts(scheme: "https", host: "waypoint.example.com", port: 0, isMainFrame: true, server: home))
        XCTAssertTrue(BridgeOrigin.accepts(scheme: "HTTPS", host: "Waypoint.Example.com", port: 443, isMainFrame: true, server: home))
        XCTAssertTrue(BridgeOrigin.accepts(scheme: "http", host: "192.168.1.20", port: 8080, isMainFrame: true, server: URL(string: "http://192.168.1.20:8080")!))
    }

    func testTheCachedPageIsTrusted() {
        XCTAssertTrue(BridgeOrigin.accepts(scheme: "waypoint-offline", host: "waypoint.offline", port: 0, isMainFrame: true, server: home))
    }

    func testNothingElseIsTrusted() {
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "https", host: "waypoint.example.com", port: 0, isMainFrame: false, server: home), "a frame is not the main page")
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "https", host: "evil.example.com", port: 0, isMainFrame: true, server: home))
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "http", host: "waypoint.example.com", port: 0, isMainFrame: true, server: home))
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "https", host: "waypoint.example.com", port: 8443, isMainFrame: true, server: home))
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "waypoint-offline", host: "evil.example", port: 0, isMainFrame: true, server: home))
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "waypoint-offline", host: "waypoint.offline", port: 0, isMainFrame: false, server: home))
        XCTAssertFalse(BridgeOrigin.accepts(scheme: "file", host: "", port: 0, isMainFrame: true, server: home))
    }
}
