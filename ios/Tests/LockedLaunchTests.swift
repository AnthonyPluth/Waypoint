import XCTest
@testable import Waypoint

private final class SwitchableKeychain: KeychainReading, @unchecked Sendable {
    var available = false
    let items: [String: Data]

    init(items: [String: Data]) {
        self.items = items
    }

    func read(_ key: String) -> KeychainRead {
        guard available else { return .unavailable }
        if let data = items[key] { return .found(data) }
        return .missing
    }
}

final class LockedLaunchTests: XCTestCase {
    private var root: URL!
    private var store: OfflineStore!
    private var pages: OfflinePages!
    private let home = URL(string: "https://waypoint.example.com")!

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("locked-launch-\(UUID().uuidString)", isDirectory: true)
        store = OfflineStore(root: root, calendar: ArrivalFixtures.utc, now: { ArrivalFixtures.moment(2026, 11, 10, 12) })
        pages = OfflinePages(root: root.appendingPathComponent("pages"))
    }

    override func tearDown() {
        try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: tripsFile.path)
        try? FileManager.default.removeItem(at: root)
        super.tearDown()
    }

    private var tripsFile: URL {
        root.appendingPathComponent(OfflineStore.folderName(for: home), isDirectory: true).appendingPathComponent("trips.json")
    }

    private func saveCopy() throws {
        try store.save(ArrivalFixtures.tripsJSON([ArrivalFixtures.parking()]), version: 1, for: home)
        try pages.save([OfflinePageFiles.index: Data("page".utf8)], build: "b", for: home)
    }

    private func lock() throws {
        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: tripsFile.path)
    }

    private func unlock() throws {
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: tripsFile.path)
    }

    func testACopyThatCannotBeReadWhileTheDeviceIsLockedIsKept() throws {
        try saveCopy()
        try lock()
        XCTAssertNil(store.load(server: home))
        XCTAssertTrue(store.isLocked(server: home))
        XCTAssertTrue(FileManager.default.fileExists(atPath: tripsFile.path))
        try unlock()
        XCTAssertNotNil(store.load(server: home))
        XCTAssertFalse(store.isLocked(server: home))
    }

    func testTheGateKeepsTheSavedCopyAndTheCachedPageWhileLocked() throws {
        try saveCopy()
        try lock()
        let gate = OfflineGate(store: store, pages: pages)
        XCTAssertFalse(gate.canShowCachedPage(for: home))
        XCTAssertTrue(pages.hasPage(for: home))
        try unlock()
        XCTAssertTrue(gate.canShowCachedPage(for: home))
    }

    func testACopyThatIsReadableButBrokenIsStillDeleted() throws {
        try saveCopy()
        try Data("not json".utf8).write(to: tripsFile)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(FileManager.default.fileExists(atPath: tripsFile.path))
    }

    func testALaunchStartsOnlyWhileActiveAndUnlockedAndOnlyOnce() {
        let gate = LaunchGate()
        XCTAssertFalse(gate.begin(active: false, protectedDataAvailable: true))
        XCTAssertFalse(gate.begin(active: true, protectedDataAvailable: false))
        XCTAssertTrue(gate.begin(active: true, protectedDataAvailable: true))
        XCTAssertFalse(gate.begin(active: true, protectedDataAvailable: true))
        gate.end()
        XCTAssertTrue(gate.begin(active: true, protectedDataAvailable: true))
    }

    func testASecondBeginIsRefusedWhileALaunchRunsAndEndAllowsOneAgain() {
        let gate = LaunchGate()
        XCTAssertTrue(gate.begin(active: true, protectedDataAvailable: true))
        XCTAssertFalse(gate.begin(active: false, protectedDataAvailable: true))
        XCTAssertFalse(gate.begin(active: true, protectedDataAvailable: true))
        gate.end()
        XCTAssertTrue(gate.begin(active: true, protectedDataAvailable: true))
    }

    private func offlineSync() -> OfflineSync {
        OfflineSync(store: store, settings: OfflineSettings(defaults: UserDefaults(suiteName: "locked-\(UUID().uuidString)")!), pages: pages,
                    server: { nil }, bearer: { nil })
    }

    func testAKeychainThatCannotBeReadAtInitIsNotKeptAsNoServerAndTheSavedTripsStay() async throws {
        try saveCopy()
        let tokens = Tokens(accessToken: "wpa_held", refreshToken: "wpr_held", expiresAt: Date().addingTimeInterval(3600))
        let keychain = SwitchableKeychain(items: ["server": Data(home.absoluteString.utf8), "tokens": try JSONEncoder().encode(tokens)])
        let session = ServerSession(offline: offlineSync(), keychain: keychain)
        let before = await session.standing()
        XCTAssertEqual(before, .unknown)
        let none = await session.server
        XCTAssertNil(none)
        XCTAssertNotNil(store.load(server: home))
        keychain.available = true
        let after = await session.standing()
        XCTAssertEqual(after, .connected)
        let found = await session.server
        XCTAssertEqual(found, home)
        XCTAssertNotNil(store.load(server: home))
    }

    func testOnlyAReadableKeychainWithNothingInItIsNotConnected() async {
        let keychain = SwitchableKeychain(items: [:])
        let session = ServerSession(offline: offlineSync(), keychain: keychain)
        let locked = await session.standing()
        XCTAssertEqual(locked, .unknown)
        keychain.available = true
        let readable = await session.standing()
        XCTAssertEqual(readable, .notConnected)
    }

    func testTheWatchKeepsItsRegionsWhileTheCredentialsCannotBeReadAndClearsThemOnceKnownWithNoServer() async {
        let phone = ArrivalRig()
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot]
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
        let known = ArrivalFlag(false)
        let blind = ArrivalWatch(store: phone.store, places: phone.places, locations: phone.locations, notifications: phone.notifications,
                                 asks: ArrivalAsks(defaults: phone.defaults), settings: OfflineSettings(defaults: phone.defaults),
                                 server: { nil }, credentialsKnown: { known.value })
        await blind.handle(.authorizationChanged)
        await blind.activated()
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
        known.value = true
        await blind.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds, [])
        phone.cleanUp()
    }
}
