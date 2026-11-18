import XCTest
@testable import Waypoint

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

    func testALaunchOpensOnlyWhileActiveAndUnlocked() {
        XCTAssertTrue(LaunchGuard.mayOpen(active: true, protectedDataAvailable: true))
        XCTAssertFalse(LaunchGuard.mayOpen(active: false, protectedDataAvailable: true))
        XCTAssertFalse(LaunchGuard.mayOpen(active: true, protectedDataAvailable: false))
        XCTAssertFalse(LaunchGuard.mayOpen(active: false, protectedDataAvailable: false))
    }
}
