import XCTest
@testable import Waypoint

final class OfflinePagesTests: XCTestCase {
    private var root: URL!
    private var pages: OfflinePages!
    private let home = URL(string: "https://waypoint.example.com")!
    private let cabin = URL(string: "http://192.168.1.20:8080")!

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("offline-pages-\(UUID().uuidString)", isDirectory: true)
        pages = OfflinePages(root: root)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        super.tearDown()
    }

    private func set(_ index: String, assets: [String: String] = [:]) -> [String: Data] {
        var contents = ["/": Data(index.utf8)]
        for (path, text) in assets { contents[path] = Data(text.utf8) }
        return contents
    }

    private func saved(under folder: URL) -> [URL] {
        let walker = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: [.isRegularFileKey])
        return (walker?.allObjects as? [URL] ?? []).filter { (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
    }

    func testSavesAndReadsTheFiles() throws {
        try pages.save(set("<html>one</html>", assets: ["/assets/app-1.js": "console.log(1)"]), build: "b1", for: home)
        XCTAssertEqual(pages.build(for: home), "b1")
        XCTAssertTrue(pages.hasPage(for: home))
        XCTAssertEqual(pages.file("/", for: home), Data("<html>one</html>".utf8))
        XCTAssertEqual(pages.file("/assets/app-1.js", for: home), Data("console.log(1)".utf8))
        XCTAssertEqual(pages.paths(for: home), ["/", "/assets/app-1.js"])
    }

    func testASaveReplacesTheWholeSet() throws {
        try pages.save(set("old", assets: ["/assets/app-1.js": "1", "/assets/chunk-1.js": "c"]), build: "b1", for: home)
        try pages.save(set("new", assets: ["/assets/app-2.js": "2"]), build: "b2", for: home)
        XCTAssertEqual(pages.build(for: home), "b2")
        XCTAssertEqual(pages.file("/", for: home), Data("new".utf8))
        XCTAssertNil(pages.file("/assets/app-1.js", for: home))
        XCTAssertNil(pages.file("/assets/chunk-1.js", for: home))
        XCTAssertEqual(pages.file("/assets/app-2.js", for: home), Data("2".utf8))
        XCTAssertEqual(saved(under: root).count, 3)
    }

    func testASaveNeedsTheAppShell() {
        XCTAssertThrowsError(try pages.save(["/assets/app-1.js": Data("1".utf8)], build: "b1", for: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testServersAreKeptApart() throws {
        try pages.save(set("home"), build: "h", for: home)
        try pages.save(set("cabin"), build: "c", for: cabin)
        XCTAssertEqual(pages.file("/", for: home), Data("home".utf8))
        XCTAssertEqual(pages.file("/", for: cabin), Data("cabin".utf8))
        pages.purge(server: home)
        XCTAssertFalse(pages.hasPage(for: home))
        XCTAssertTrue(pages.hasPage(for: cabin))
    }

    func testPurgeAllRemovesEveryServer() throws {
        try pages.save(set("home"), build: "h", for: home)
        try pages.save(set("cabin"), build: "c", for: cabin)
        try pages.purgeAll()
        XCTAssertFalse(pages.hasPage(for: home))
        XCTAssertFalse(pages.hasPage(for: cabin))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }

    func testPurgingNothingIsFine() throws {
        pages.purge(server: home)
        XCTAssertNoThrow(try pages.purgeAll())
    }

    func testOnlySavedPathsAreServed() throws {
        try pages.save(set("home", assets: ["/assets/app-1.js": "1"]), build: "b1", for: home)
        XCTAssertNil(pages.file("/assets/other.js", for: home))
        XCTAssertNil(pages.file("/assets/../../etc/passwd", for: home))
        XCTAssertNil(pages.file("/meta.json", for: home))
    }

    func testAMissingFileReadsAsNothing() throws {
        try pages.save(set("home", assets: ["/assets/app-1.js": "1"]), build: "b1", for: home)
        let folder = root.appendingPathComponent(OfflineStore.folderName(for: home))
        for file in saved(under: folder) where file.lastPathComponent.hasPrefix("f-") { try? FileManager.default.removeItem(at: file) }
        XCTAssertNil(pages.file("/", for: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testSavedFilesCarryCompleteFileProtection() throws {
        try pages.save(set("home", assets: ["/assets/app-1.js": "1"]), build: "b1", for: home)
        let files = saved(under: root)
        XCTAssertEqual(files.count, 3)
        for file in files {
            let value = try FileManager.default.attributesOfItem(atPath: file.path)[.protectionKey] as? FileProtectionType
            #if targetEnvironment(simulator)
            if let value { XCTAssertEqual(value, .complete, file.lastPathComponent) }
            #else
            XCTAssertEqual(value, .complete, file.lastPathComponent)
            #endif
        }
    }

    func testTheDefaultFolderIsInApplicationSupport() {
        XCTAssertTrue(OfflinePages.defaultRoot.path.contains("Application Support"))
    }

    func testAssetPathsAreCheckedBeforeTheyAreFetched() {
        XCTAssertTrue(OfflinePageFiles.isAssetPath("/assets/index-Ab_12.js"))
        XCTAssertTrue(OfflinePageFiles.isAssetPath("/assets/fonts/inter.woff2"))
        XCTAssertFalse(OfflinePageFiles.isAssetPath("/api/trips"))
        XCTAssertFalse(OfflinePageFiles.isAssetPath("/assets/../api/trips"))
        XCTAssertFalse(OfflinePageFiles.isAssetPath("/assets/a?b=1"))
        XCTAssertFalse(OfflinePageFiles.isAssetPath("/assets/a b.js"))
        XCTAssertFalse(OfflinePageFiles.isAssetPath("assets/a.js"))
        XCTAssertFalse(OfflinePageFiles.isAssetPath("/assets/" + String(repeating: "a", count: 300)))
    }

    func testLoadedAssetPathsAreTheServersOwnAssetsOnly() {
        let names = [
            "https://waypoint.example.com/assets/index-1.js",
            "https://waypoint.example.com/assets/index-1.js",
            "https://waypoint.example.com/assets/index-1.css?v=2",
            "https://waypoint.example.com/api/trips",
            "https://other.example.com/assets/evil.js",
            "http://waypoint.example.com/assets/downgrade.js",
            "not a url",
        ]
        XCTAssertEqual(OfflinePageFiles.assetPaths(in: names, origin: home), ["/assets/index-1.css", "/assets/index-1.js"])
    }

    func testTheContentTypesTheWebViewNeeds() {
        XCTAssertEqual(OfflinePageFiles.mimeType(for: "/"), "text/html; charset=utf-8")
        XCTAssertEqual(OfflinePageFiles.mimeType(for: "/assets/a.js"), "text/javascript; charset=utf-8")
        XCTAssertEqual(OfflinePageFiles.mimeType(for: "/assets/a.css"), "text/css; charset=utf-8")
        XCTAssertEqual(OfflinePageFiles.mimeType(for: "/fonts/Inter-Variable.woff2"), "font/woff2")
        XCTAssertEqual(OfflinePageFiles.mimeType(for: "/logo.svg"), "image/svg+xml")
        XCTAssertEqual(OfflinePageFiles.mimeType(for: "/manifest.webmanifest"), "application/manifest+json")
    }
}
