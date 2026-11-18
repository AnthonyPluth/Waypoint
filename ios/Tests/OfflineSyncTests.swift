import XCTest
@testable import Waypoint

private final class FakeFetching: OfflineFetching, @unchecked Sendable {
    var result: Result<(data: Data, status: Int), Error> = .failure(URLError(.notConnectedToInternet))
    var onFetch: (() async -> Void)?
    private(set) var calls: [(server: URL, bearer: String?)] = []

    func fetch(server: URL, bearer: String?) async throws -> (data: Data, status: Int) {
        calls.append((server, bearer))
        await onFetch?()
        return try result.get()
    }
}

private final class ParameterUpdates: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    var calls: Int {
        lock.lock()
        defer { lock.unlock() }
        return count
    }

    func record() {
        lock.lock()
        count += 1
        lock.unlock()
    }
}

private final class SyncingProbe: @unchecked Sendable {
    var value = false
}

final class OfflineSyncTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!
    private var suite: String!
    private var store: OfflineStore!
    private var fetching: FakeFetching!
    private let home = URL(string: "https://waypoint.example.com")!
    private let cabin = URL(string: "http://192.168.1.20:8080")!

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("offline-sync-\(UUID().uuidString)", isDirectory: true)
        suite = "offline-sync-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        let now = Self.utc.date(from: DateComponents(year: 2026, month: 11, day: 10, hour: 12))!
        store = OfflineStore(root: root, calendar: Self.utc, now: { now })
        fetching = FakeFetching()
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private func settings(on: Bool) -> OfflineSettings {
        let settings = OfflineSettings(defaults: defaults)
        settings.set(on)
        return settings
    }

    private func makeSync(on: Bool = true, server: URL? = nil, bearer: String? = "wpa_token",
                          tokenError: Error? = nil, updates: ParameterUpdates? = nil) -> OfflineSync {
        let chosen = server ?? home
        return OfflineSync(store: store, settings: settings(on: on), fetching: fetching,
                           server: { chosen }, bearer: {
                               if let tokenError { throw tokenError }
                               return bearer
                           }, parametersChanged: { updates?.record() })
    }

    private func reply(_ names: [String], version: Int = 1) -> Data {
        let entries: [[String: Any]] = names.enumerated().map { index, name in
            ["trip": ["id": index + 1, "name": name, "start_date": "2026-12-01", "end_date": "2026-12-08"] as [String: Any],
             "messages": [] as [Any]]
        }
        return try! JSONSerialization.data(withJSONObject: ["version": version, "trips": entries])
    }

    private func answer(_ names: [String], version: Int = 1, status: Int = 200) {
        fetching.result = .success((reply(names, version: version), status))
    }

    private func savedNames() -> [String] {
        store.tripNames(server: home)
    }

    func testSavingStartsOn() {
        XCTAssertTrue(OfflineSettings(defaults: defaults).isOn)
    }

    func testAnUntouchedInstallSavesAtTheFirstSync() async {
        answer(["Lisbon"])
        let sync = OfflineSync(store: store, settings: OfflineSettings(defaults: defaults), fetching: fetching,
                               server: { [home] in home }, bearer: { "wpa_token" })
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testSigningInAgainFindsSavingOnAfterItWasSwitchedOff() async {
        let sync = makeSync()
        await sync.setSaving(false)
        XCTAssertFalse(OfflineSettings(defaults: defaults).isOn)
        await sync.signedOut()
        XCTAssertTrue(OfflineSettings(defaults: defaults).isOn)
    }

    func testSyncingIsTrueOnlyWhileAFetchRuns() async {
        answer(["Lisbon"])
        let sync = makeSync()
        XCTAssertFalse(sync.state.syncing)
        let during = SyncingProbe()
        fetching.onFetch = { during.value = sync.state.syncing }
        await sync.sync()
        XCTAssertTrue(during.value)
        XCTAssertFalse(sync.state.syncing)
    }

    func testAFailedSaveSetsLastSaveFailedAndTheNextSuccessClearsIt() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        XCTAssertFalse(sync.state.lastSaveFailed)
        answer([], status: 500)
        await sync.sync()
        XCTAssertTrue(sync.state.lastSaveFailed)
        XCTAssertEqual(savedNames(), ["Lisbon"])
        answer(["Lisbon", "Oslo"])
        await sync.sync()
        XCTAssertFalse(sync.state.lastSaveFailed)
    }

    func testAnUnknownVersionCountsAsAFailedSave() async {
        answer(["Lisbon"], version: 2)
        let sync = makeSync()
        await sync.sync()
        XCTAssertTrue(sync.state.lastSaveFailed)
    }

    func testSwitchingSavingOffClearsLastSaveFailed() async {
        answer([], status: 500)
        let sync = makeSync()
        await sync.sync()
        XCTAssertTrue(sync.state.lastSaveFailed)
        await sync.setSaving(false)
        XCTAssertFalse(sync.state.lastSaveFailed)
    }

    func testAFetchThatFailsAfterAPurgeLeavesLastSaveFailedFalse() async {
        let sync = makeSync()
        fetching.onFetch = { await sync.purge() }
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertFalse(sync.state.lastSaveFailed)
    }

    func testAFetchThatFailsAfterSavingIsSwitchedOffLeavesLastSaveFailedFalse() async {
        let sync = makeSync()
        fetching.onFetch = { await sync.setSaving(false) }
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertFalse(sync.state.lastSaveFailed)
    }

    func testAFetchThatFailsWithSavingStillOnSetsLastSaveFailed() async {
        let sync = makeSync()
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertTrue(sync.state.lastSaveFailed)
    }

    func testSyncSavesTheReplyWithTheBearerToken() async {
        answer(["Lisbon"])
        let outcome = await makeSync().sync()
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(savedNames(), ["Lisbon"])
        XCTAssertEqual(store.load(server: home)?.version, 1)
        XCTAssertEqual(fetching.calls.count, 1)
        XCTAssertEqual(fetching.calls.first?.server, home)
        XCTAssertEqual(fetching.calls.first?.bearer, "wpa_token")
    }

    func testSyncReplacesTheSavedSet() async {
        answer(["Lisbon", "Oslo"])
        let sync = makeSync()
        await sync.sync()
        answer(["Oslo"])
        await sync.sync()
        XCTAssertEqual(savedNames(), ["Oslo"])
    }

    func testAServerWithNoSignInIsReadWithNoToken() async {
        answer(["Lisbon"])
        let outcome = await makeSync(bearer: nil).sync()
        XCTAssertEqual(outcome, .saved)
        XCTAssertNil(fetching.calls.first?.bearer)
    }

    func testNothingIsFetchedWhileSavingIsOff() async {
        answer(["Lisbon"])
        let outcome = await makeSync(on: false).sync()
        XCTAssertEqual(outcome, .off)
        XCTAssertTrue(fetching.calls.isEmpty)
        XCTAssertEqual(savedNames(), [])
    }

    func testAnUnknownVersionKeepsTheOldCopy() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        answer(["Oslo"], version: 2)
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .unknownVersion)
        XCTAssertEqual(savedNames(), ["Lisbon"])
        XCTAssertEqual(store.load(server: home)?.version, 1)
    }

    func testAReplyWithNoVersionKeepsTheOldCopy() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        fetching.result = .success((Data(#"{"trips": []}"#.utf8), 200))
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .unknownVersion)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testAReplyThatIsNotATripSetKeepsTheOldCopy() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        fetching.result = .success((Data(#"{"version": 1}"#.utf8), 200))
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testA401PurgesTheSavedTrips() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        answer([], status: 401)
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .unauthorized)
        XCTAssertNil(store.load(server: home))
    }

    func testA403PurgesTheSavedTrips() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        answer([], status: 403)
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .unauthorized)
        XCTAssertNil(store.load(server: home))
    }

    func testASignInThatEndedPurgesTheSavedTrips() async {
        answer(["Lisbon"])
        await makeSync().sync()
        let outcome = await makeSync(tokenError: ServerError.signedOut).sync()
        XCTAssertEqual(outcome, .unauthorized)
        XCTAssertNil(store.load(server: home))
    }

    func testANetworkErrorKeepsTheCopy() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        fetching.result = .failure(ServerError.notReachable("offline"))
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testATokenRenewalThatCannotReachTheServerKeepsTheCopy() async {
        answer(["Lisbon"])
        await makeSync().sync()
        let outcome = await makeSync(tokenError: ServerError.notReachable("offline")).sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testAServerErrorKeepsTheCopy() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        answer([], status: 500)
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .failed)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testNoServerPurges() async {
        answer(["Lisbon"])
        await makeSync().sync()
        let sync = OfflineSync(store: store, settings: settings(on: true), fetching: fetching,
                               server: { nil }, bearer: { nil })
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .noServer)
        XCTAssertNil(store.load(server: home))
    }

    func testAPurgeDuringAFetchStopsTheSave() async {
        answer(["Lisbon"])
        let sync = makeSync()
        fetching.onFetch = { await sync.purge() }
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .superseded)
        XCTAssertNil(store.load(server: home))
    }

    func testTurningSavingOffDuringAFetchStopsTheSave() async {
        answer(["Lisbon"])
        let sync = makeSync()
        fetching.onFetch = { await sync.setSaving(false) }
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .superseded)
        XCTAssertNil(store.load(server: home))
    }

    func testTurningSavingOffPurges() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        await sync.setSaving(false)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(OfflineSettings(defaults: defaults).isOn)
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .off)
    }

    func testTurningSavingOnLetsTheNextSyncSave() async {
        answer(["Lisbon"])
        let sync = makeSync(on: false)
        await sync.setSaving(true)
        let outcome = await sync.sync()
        XCTAssertEqual(outcome, .saved)
    }

    func testRemovePurgesAndLeavesSavingOn() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        await sync.remove()
        XCTAssertNil(store.load(server: home))
        XCTAssertTrue(OfflineSettings(defaults: defaults).isOn)
    }

    func testAChangedServerPurges() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        await sync.serverChanged(from: home, to: cabin)
        XCTAssertNil(store.load(server: home))
    }

    func testTheSameServerWrittenAnotherWayKeepsTheCopy() async {
        answer(["Lisbon"])
        let sync = makeSync()
        await sync.sync()
        await sync.serverChanged(from: home, to: URL(string: "https://Waypoint.Example.com/")!)
        await sync.serverChanged(from: nil, to: cabin)
        XCTAssertEqual(savedNames(), ["Lisbon"])
    }

    func testSigningOutPurges() async {
        answer(["Lisbon"])
        await makeSync().sync()
        let session = ServerSession(offline: OfflineSync(store: store, settings: settings(on: true), fetching: fetching,
                                                         server: { nil }, bearer: { nil }))
        await session.signOut()
        XCTAssertNil(store.load(server: home))
    }

    // MARK: Siri's list of places follows the saved trips

    func testEverySaveUpdatesTheShortcutParameters() async {
        let updates = ParameterUpdates()
        let sync = makeSync(updates: updates)
        answer(["Lisbon"])
        await sync.sync()
        XCTAssertEqual(updates.calls, 1)
        answer(["Lisbon", "Oslo"])
        await sync.sync()
        XCTAssertEqual(updates.calls, 2)
    }

    func testAFailedOrRefusedSaveDoesNotUpdateTheParameters() async {
        let updates = ParameterUpdates()
        let sync = makeSync(updates: updates)
        answer([], status: 500)
        await sync.sync()
        answer(["Lisbon"], version: 2)
        await sync.sync()
        XCTAssertEqual(updates.calls, 0)
    }

    func testEveryKindOfPurgeUpdatesTheParametersAfterTheCopyIsGone() async {
        answer(["Lisbon"])
        let oldServer = home
        let newServer = cabin
        let kinds: [(String, (OfflineSync) async -> Void)] = [
            ("sign-out", { sync in await sync.signedOut() }),
            ("saving off", { sync in await sync.setSaving(false) }),
            ("remove", { sync in await sync.remove() }),
            ("changed server", { sync in await sync.serverChanged(from: oldServer, to: newServer) }),
        ]
        for (name, purge) in kinds {
            let updates = ParameterUpdates()
            let sync = makeSync(updates: updates)
            await sync.sync()
            XCTAssertEqual(savedNames(), ["Lisbon"], name)
            let before = updates.calls
            await purge(sync)
            XCTAssertEqual(updates.calls, before + 1, name)
            XCTAssertEqual(savedNames(), [], name)
        }
    }

    func testA401AndA403PurgeAndUpdateTheParameters() async {
        for status in [401, 403] {
            let updates = ParameterUpdates()
            let sync = makeSync(updates: updates)
            answer(["Lisbon"])
            await sync.sync()
            answer([], status: status)
            await sync.sync()
            XCTAssertEqual(updates.calls, 2, "\(status)")
            XCTAssertEqual(savedNames(), [], "\(status)")
        }
    }

    func testAnExpiredSessionPurgesAndUpdatesTheParameters() async {
        let updates = ParameterUpdates()
        let sync = makeSync(tokenError: ServerError.signedOut, updates: updates)
        await sync.sync()
        XCTAssertEqual(updates.calls, 1)
    }

    func testNoServerPurgesAndUpdatesTheParameters() async {
        let updates = ParameterUpdates()
        let sync = OfflineSync(store: store, settings: settings(on: true), fetching: fetching,
                               server: { nil }, bearer: { "wpa_token" }, parametersChanged: { updates.record() })
        await sync.sync()
        XCTAssertEqual(updates.calls, 1)
    }
}
