import XCTest
@testable import Waypoint

private final class FakePages: PageFetching, @unchecked Sendable {
    var files: [String: PageReply] = [:]
    var failing: Set<String> = []
    var onGet: ((String) async -> Void)?
    var requested: [String] = []

    func serve(_ path: String, _ text: String, status: Int = 200, finalPath: String? = nil, host: String = "waypoint.example.com") {
        files[path] = PageReply(data: Data(text.utf8), status: status, url: URL(string: "https://\(host)\(finalPath ?? path)"))
    }

    func get(_ url: URL) async throws -> PageReply {
        let path = url.path.isEmpty ? "/" : url.path
        requested.append(path)
        await onGet?(path)
        if failing.contains(path) { throw URLError(.notConnectedToInternet) }
        guard let reply = files[path] else { return PageReply(data: Data("not found".utf8), status: 404, url: url) }
        return reply
    }
}

final class OfflinePageSyncTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!
    private var suite: String!
    private var store: OfflineStore!
    private var pages: OfflinePages!
    private var network: FakePages!
    private let home = URL(string: "https://waypoint.example.com")!

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("offline-page-sync-\(UUID().uuidString)", isDirectory: true)
        suite = "offline-page-sync-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        store = TripFixtures.store(at: root.appendingPathComponent("trips"))
        pages = OfflinePages(root: root.appendingPathComponent("pages"))
        network = FakePages()
        network.serve("/", "<html>build one</html>")
        network.serve("/assets/index-1.js", "one")
        network.serve("/assets/chunk-1.js", "chunk")
        network.serve("/logo.svg", "<svg/>")
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private func makeSync(on: Bool = true, server: URL? = nil) -> OfflineSync {
        let settings = OfflineSettings(defaults: defaults)
        settings.set(on)
        let chosen = server ?? home
        return OfflineSync(store: store, settings: settings, pages: pages, pageFetching: network,
                           server: { chosen }, bearer: { "wpa_token" })
    }

    private func saveTrips() throws {
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: home)
    }

    func testTheAppShellAndTheLoadedAssetsAreSaved() async {
        let outcome = await makeSync().refreshPages(loaded: ["/assets/index-1.js", "/assets/chunk-1.js"])
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(pages.file("/", for: home), Data("<html>build one</html>".utf8))
        XCTAssertEqual(pages.file("/assets/index-1.js", for: home), Data("one".utf8))
        XCTAssertEqual(pages.file("/assets/chunk-1.js", for: home), Data("chunk".utf8))
        XCTAssertEqual(pages.file("/logo.svg", for: home), Data("<svg/>".utf8))
        XCTAssertNil(pages.file("/fonts/Inter-Variable.woff2", for: home), "a shell file the server does not have is skipped, not fatal")
    }

    func testNothingIsFetchedWhileSavingIsOff() async {
        let outcome = await makeSync(on: false).refreshPages(loaded: ["/assets/index-1.js"])
        XCTAssertEqual(outcome, .off)
        XCTAssertTrue(network.requested.isEmpty)
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testOnlyPublicFilesAreAskedForAndWithoutAnyToken() async {
        await makeSync().refreshPages(loaded: ["/assets/index-1.js", "/api/trips", "/assets/../api/offline", "https://evil.example/assets/x.js"])
        XCTAssertFalse(network.requested.contains { $0.hasPrefix("/api") })
        XCTAssertTrue(network.requested.allSatisfy { $0 == "/" || $0 == "/assets/index-1.js" || OfflinePageFiles.shell.contains($0) })
    }

    func testTheSameBuildIsNotDownloadedAgain() async {
        let sync = makeSync()
        await sync.refreshPages(loaded: ["/assets/index-1.js"])
        let before = network.requested.count
        let outcome = await sync.refreshPages(loaded: ["/assets/index-1.js"])
        XCTAssertEqual(outcome, .current)
        XCTAssertEqual(network.requested.count - before, 1, "only the app shell is read to see the build")
    }

    func testANewBuildReplacesEverything() async {
        let sync = makeSync()
        await sync.refreshPages(loaded: ["/assets/index-1.js", "/assets/chunk-1.js"])
        network.serve("/", "<html>build two</html>")
        network.serve("/assets/index-2.js", "two")
        let outcome = await sync.refreshPages(loaded: ["/assets/index-2.js"])
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(pages.file("/", for: home), Data("<html>build two</html>".utf8))
        XCTAssertEqual(pages.file("/assets/index-2.js", for: home), Data("two".utf8))
        XCTAssertNil(pages.file("/assets/index-1.js", for: home))
        XCTAssertNil(pages.file("/assets/chunk-1.js", for: home))
    }

    func testANewAssetOfTheSameBuildIsAddedWithoutLosingTheOthers() async {
        let sync = makeSync()
        await sync.refreshPages(loaded: ["/assets/index-1.js"])
        network.requested.removeAll()
        let outcome = await sync.refreshPages(loaded: ["/assets/index-1.js", "/assets/chunk-1.js"])
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(pages.file("/assets/index-1.js", for: home), Data("one".utf8))
        XCTAssertEqual(pages.file("/assets/chunk-1.js", for: home), Data("chunk".utf8))
        XCTAssertFalse(network.requested.contains("/assets/index-1.js"), "a file already kept is not fetched again")
    }

    func testAnAssetThatCannotBeReadKeepsTheOldCopy() async {
        let sync = makeSync()
        await sync.refreshPages(loaded: ["/assets/index-1.js"])
        let build = pages.build(for: home)
        network.serve("/", "<html>build two</html>")
        let outcome = await sync.refreshPages(loaded: ["/assets/missing-2.js"])
        XCTAssertEqual(outcome, .failed)
        XCTAssertEqual(pages.file("/", for: home), Data("<html>build one</html>".utf8))
        XCTAssertEqual(pages.build(for: home), build)
        XCTAssertNotNil(pages.file("/assets/index-1.js", for: home))
    }

    func testANetworkErrorKeepsTheOldCopy() async {
        let sync = makeSync()
        await sync.refreshPages(loaded: ["/assets/index-1.js"])
        network.failing = ["/"]
        let outcome = await sync.refreshPages(loaded: ["/assets/index-1.js"])
        XCTAssertEqual(outcome, .failed)
        XCTAssertTrue(pages.hasPage(for: home))
    }

    func testAnAppShellThatIsNotA200IsNotSaved() async {
        network.serve("/", "<html>error</html>", status: 500)
        let outcome = await makeSync().refreshPages(loaded: [])
        XCTAssertEqual(outcome, .failed)
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testAnAppShellThatWasRedirectedAwayIsNotSaved() async {
        network.serve("/", "<html>sign in</html>", finalPath: "/login")
        let signIn = await makeSync().refreshPages(loaded: [])
        XCTAssertEqual(signIn, .failed)
        network.serve("/", "<html>elsewhere</html>", host: "login.example.com")
        let elsewhere = await makeSync().refreshPages(loaded: [])
        XCTAssertEqual(elsewhere, .failed)
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testRemoveDeletesThePagesWithTheTrips() async throws {
        let sync = makeSync()
        try saveTrips()
        await sync.refreshPages(loaded: ["/assets/index-1.js"])
        await sync.remove()
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testTurningSavingOffDeletesThePagesWithTheTrips() async throws {
        let sync = makeSync()
        try saveTrips()
        await sync.refreshPages(loaded: ["/assets/index-1.js"])
        await sync.setSaving(false)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testAChangedServerDeletesThePages() async {
        let sync = makeSync()
        await sync.refreshPages(loaded: [])
        await sync.serverChanged(from: home, to: URL(string: "https://other.example.com")!)
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testPurgeDuringADownloadStopsTheSave() async {
        let sync = makeSync()
        network.onGet = { path in
            if path == "/assets/index-1.js" { await sync.remove() }
        }
        let outcome = await sync.refreshPages(loaded: ["/assets/index-1.js"])
        XCTAssertEqual(outcome, .superseded)
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testTurningSavingOffDuringADownloadStopsTheSave() async {
        let sync = makeSync()
        let settings = OfflineSettings(defaults: defaults)
        network.onGet = { path in
            if path == "/assets/index-1.js" { settings.set(false) }
        }
        let outcome = await sync.refreshPages(loaded: ["/assets/index-1.js"])
        XCTAssertEqual(outcome, .superseded)
        XCTAssertFalse(pages.hasPage(for: home))
    }
}
