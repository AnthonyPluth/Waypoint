import WebKit
import XCTest
@testable import Waypoint

private final class FakeTask: NSObject, WKURLSchemeTask {
    let request: URLRequest
    private(set) var response: HTTPURLResponse?
    private(set) var body = Data()
    private(set) var finished = false
    private(set) var failure: Error?

    init(_ url: String, method: String = "GET") {
        var request = URLRequest(url: URL(string: url)!)
        request.httpMethod = method
        self.request = request
    }

    func didReceive(_ response: URLResponse) { self.response = response as? HTTPURLResponse }
    func didReceive(_ data: Data) { body.append(data) }
    func didFinish() { finished = true }
    func didFailWithError(_ error: Error) { failure = error }

    var text: String { String(decoding: body, as: UTF8.self) }
}

private final class LoadWaiter: NSObject, WKNavigationDelegate {
    private var continuation: CheckedContinuation<Void, Error>?

    func load(_ url: URL, in webView: WKWebView) async throws {
        webView.navigationDelegate = self
        try await withCheckedThrowingContinuation { (next: CheckedContinuation<Void, Error>) in
            continuation = next
            webView.load(URLRequest(url: url))
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        continuation?.resume()
        continuation = nil
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        continuation?.resume(throwing: error)
        continuation = nil
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        continuation?.resume(throwing: error)
        continuation = nil
    }
}

final class OfflineShellTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!
    private var suite: String!
    private var store: OfflineStore!
    private var pages: OfflinePages!
    private var gate: OfflineGate!
    private let home = URL(string: "https://waypoint.example.com")!

    private static let index = """
    <!doctype html><html><head><title>cached shell</title></head><body><div id="app">cached</div>\
    <script src="/assets/app-1.js"></script></body></html>
    """
    private static let script = "document.documentElement.dataset.ran = 'yes';"

    private static func closedPort() -> UInt16 {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(descriptor) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        address.sin_port = 0
        _ = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(descriptor, $0, &length) }
        }
        return UInt16(bigEndian: address.sin_port)
    }

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("offline-shell-\(UUID().uuidString)", isDirectory: true)
        suite = "offline-shell-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        store = TripFixtures.store(at: root.appendingPathComponent("trips"))
        pages = OfflinePages(root: root.appendingPathComponent("pages"))
        gate = OfflineGate(store: store, pages: pages)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private func savePages(for server: URL? = nil) throws {
        try pages.save(["/": Data(Self.index.utf8), "/assets/app-1.js": Data(Self.script.utf8)], build: "b1", for: server ?? home)
    }

    private func saveTrips(for server: URL? = nil) throws {
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: server ?? home)
    }

    func testTheGateOpensOnlyWithSavedTripsAndASavedPage() throws {
        XCTAssertFalse(gate.canShowCachedPage(for: home))
        try saveTrips()
        XCTAssertFalse(gate.canShowCachedPage(for: home), "saved trips alone have no page to show")
        try savePages()
        XCTAssertTrue(gate.canShowCachedPage(for: home))
        XCTAssertEqual(gate.file("/assets/app-1.js", for: home), Data(Self.script.utf8))
    }

    func testTheGateStaysShutAndDeletesThePagesWithoutSavedTrips() throws {
        try savePages()
        XCTAssertFalse(gate.canShowCachedPage(for: home))
        XCTAssertNil(gate.file("/", for: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testTheGateShutsWhenEveryTripHasExpired() throws {
        try store.save(TripFixtures.reply(["Lisbon"], end: "2026-11-05"), version: 1, for: home)
        try savePages()
        let later = TripFixtures.store(at: root.appendingPathComponent("trips"), now: TripFixtures.utc.date(from: DateComponents(year: 2026, month: 11, day: 9, hour: 12))!)
        XCTAssertFalse(OfflineGate(store: later, pages: pages).canShowCachedPage(for: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    func testTheGateIsPerServer() throws {
        try saveTrips()
        try savePages()
        XCTAssertFalse(gate.canShowCachedPage(for: URL(string: "https://other.example.com")!))
    }

    func testTheCachedPageIsShownWhenTheServerCannotBeReachedAndTripsAreSaved() throws {
        try saveTrips()
        try savePages()
        for code in [URLError.Code.notConnectedToInternet, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed, .timedOut, .networkConnectionLost] {
            XCTAssertTrue(OfflineFallback.shouldShowCachedPage(error: URLError(code), failedURL: home, server: home, gate: gate), "\(code)")
        }
    }

    func testTheCachedPageIsNotShownWhenTheServerAnswersOrFailsForAnotherReason() throws {
        try saveTrips()
        try savePages()
        for code in [URLError.Code.cancelled, .serverCertificateUntrusted, .badServerResponse, .secureConnectionFailed, .appTransportSecurityRequiresSecureConnection] {
            XCTAssertFalse(OfflineFallback.shouldShowCachedPage(error: URLError(code), failedURL: home, server: home, gate: gate), "\(code)")
        }
        XCTAssertFalse(OfflineFallback.shouldShowCachedPage(error: NSError(domain: "Other", code: -1009), failedURL: home, server: home, gate: gate))
    }

    func testTheCachedPageIsNotShownWithoutSavedTrips() throws {
        try savePages()
        XCTAssertFalse(OfflineFallback.shouldShowCachedPage(error: URLError(.notConnectedToInternet), failedURL: home, server: home, gate: gate))
    }

    func testTheCachedPageIsNotShownForAnotherAddress() throws {
        try saveTrips()
        try savePages()
        let elsewhere = URL(string: "https://elsewhere.example.com/")!
        XCTAssertFalse(OfflineFallback.shouldShowCachedPage(error: URLError(.notConnectedToInternet), failedURL: elsewhere, server: home, gate: gate))
    }

    @MainActor
    func testTheSchemeHandlerServesTheSavedPageAndAssets() throws {
        try saveTrips()
        try savePages()
        let handler = OfflinePageHandler(server: home, gate: gate)
        let page = FakeTask("waypoint-offline://waypoint.offline/")
        handler.webView(WKWebView(), start: page)
        XCTAssertTrue(page.finished)
        XCTAssertEqual(page.response?.statusCode, 200)
        XCTAssertEqual(page.response?.value(forHTTPHeaderField: "Content-Type"), "text/html; charset=utf-8")
        XCTAssertEqual(page.text, Self.index)
        let asset = FakeTask("waypoint-offline://waypoint.offline/assets/app-1.js?v=2")
        handler.webView(WKWebView(), start: asset)
        XCTAssertEqual(asset.response?.value(forHTTPHeaderField: "Content-Type"), "text/javascript; charset=utf-8")
        XCTAssertEqual(asset.text, Self.script)
    }

    @MainActor
    func testTheSchemeHandlerServesNothingWithoutSavedTrips() throws {
        try savePages()
        let handler = OfflinePageHandler(server: home, gate: gate)
        let page = FakeTask("waypoint-offline://waypoint.offline/")
        handler.webView(WKWebView(), start: page)
        XCTAssertFalse(page.finished)
        XCTAssertNil(page.response)
        XCTAssertEqual((page.failure as? URLError)?.code, .notConnectedToInternet)
    }

    @MainActor
    func testTheSchemeHandlerFailsEverythingItDoesNotHold() throws {
        try saveTrips()
        try savePages()
        var asked = 0
        let handler = OfflinePageHandler(server: home, gate: gate, onServerRequest: { asked += 1 })
        let missing = FakeTask("waypoint-offline://waypoint.offline/assets/other.js")
        handler.webView(WKWebView(), start: missing)
        XCTAssertEqual((missing.failure as? URLError)?.code, .notConnectedToInternet)
        XCTAssertEqual(asked, 0)
        let api = FakeTask("waypoint-offline://waypoint.offline/api/trips")
        handler.webView(WKWebView(), start: api)
        XCTAssertEqual((api.failure as? URLError)?.code, .notConnectedToInternet, "the page reads an unreachable server as offline")
        XCTAssertEqual(asked, 1)
        let post = FakeTask("waypoint-offline://waypoint.offline/", method: "POST")
        handler.webView(WKWebView(), start: post)
        XCTAssertNotNil(post.failure)
        let stranger = FakeTask("waypoint-offline://evil.example/")
        handler.webView(WKWebView(), start: stranger)
        XCTAssertNotNil(stranger.failure)
        XCTAssertNil(stranger.response)
    }

    @MainActor
    func testAPageFromTheCacheCanReadSavedTripsOverTheBridge() async throws {
        try saveTrips()
        try savePages()
        let sync = OfflineSync(store: store, settings: OfflineSettings(defaults: defaults), pages: pages, server: { [home] in home }, bearer: { nil })
        let configuration = WKWebViewConfiguration()
        configuration.setURLSchemeHandler(OfflinePageHandler(server: home, gate: gate), forURLScheme: OfflinePageAddress.scheme)
        let bridge = OfflineBridge(store: store, sync: sync, settings: OfflineSettings(defaults: defaults))
        configuration.userContentController.addScriptMessageHandler(
            OfflineBridgeHandler(server: home, bridge: bridge, currentServer: { [home] in home }),
            contentWorld: .page, name: OfflineBridgeHandler.name)
        let webView = WKWebView(frame: .zero, configuration: configuration)
        let waiter = LoadWaiter()
        try await waiter.load(OfflinePageAddress.home, in: webView)
        let title = try await webView.evaluateJavaScript("document.title") as? String
        XCTAssertEqual(title, "cached shell")
        let ran = try await webView.evaluateJavaScript("document.documentElement.dataset.ran") as? String
        XCTAssertEqual(ran, "yes")

        let post = "return await window.webkit.messageHandlers.waypointOffline.postMessage"
        let status = try await webView.callAsyncJavaScript("\(post)({ type: 'status' })", contentWorld: .page) as? [String: Any]
        XCTAssertEqual(status?["version"] as? Int, 1)
        XCTAssertEqual(status?["saving"] as? Bool, true)
        XCTAssertEqual(status?["syncing"] as? Bool, false)
        XCTAssertEqual(status?["lastSaveFailed"] as? Bool, false)
        XCTAssertEqual((status?["trips"] as? [[String: Any]])?.first?["name"] as? String, "Lisbon")
        let load = try await webView.callAsyncJavaScript("\(post)({ type: 'load' })", contentWorld: .page) as? [String: Any]
        let trip = (load?["trips"] as? [[String: Any]])?.first
        XCTAssertEqual((trip?["trip"] as? [String: Any])?["name"] as? String, "Lisbon")
        XCTAssertNotNil(trip?["savedAt"] as? Int)
        let refused = try await webView.callAsyncJavaScript(
            "try { await window.webkit.messageHandlers.waypointOffline.postMessage({ type: 'nope' }); return 'answered'; } catch (e) { return 'rejected'; }",
            contentWorld: .page) as? String
        XCTAssertEqual(refused, "rejected")
        let removed = try await webView.callAsyncJavaScript("\(post)({ type: 'remove' })", contentWorld: .page) as? [String: Any]
        XCTAssertTrue((removed?["trips"] as? [Any])?.isEmpty == true)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(pages.hasPage(for: home))
    }

    @MainActor
    func testTheBridgeAnswersNobodyWhoseSessionEnded() async throws {
        try saveTrips()
        try savePages()
        let sync = OfflineSync(store: store, settings: OfflineSettings(defaults: defaults), pages: pages, server: { nil }, bearer: { nil })
        let configuration = WKWebViewConfiguration()
        configuration.setURLSchemeHandler(OfflinePageHandler(server: home, gate: gate), forURLScheme: OfflinePageAddress.scheme)
        configuration.userContentController.addScriptMessageHandler(
            OfflineBridgeHandler(server: home, bridge: OfflineBridge(store: store, sync: sync, settings: OfflineSettings(defaults: defaults)), currentServer: { nil }),
            contentWorld: .page, name: OfflineBridgeHandler.name)
        let webView = WKWebView(frame: .zero, configuration: configuration)
        try await LoadWaiter().load(OfflinePageAddress.home, in: webView)
        let answer = try await webView.callAsyncJavaScript(
            "try { await window.webkit.messageHandlers.waypointOffline.postMessage({ type: 'load' }); return 'answered'; } catch (e) { return 'rejected'; }",
            contentWorld: .page) as? String
        XCTAssertEqual(answer, "rejected")
    }

    @MainActor
    func testTheShellShowsTheCachedPageWhenARemoteServerCannotBeReached() async throws {
        let server = URL(string: "https://127.0.0.1:\(Self.closedPort())")!
        try saveTrips(for: server)
        try savePages(for: server)
        let before = (ShellViewController.serverURL, ShellViewController.gate)
        ShellViewController.serverURL = server
        ShellViewController.gate = gate
        defer { (ShellViewController.serverURL, ShellViewController.gate) = before }
        let controller = ShellViewController()
        controller.loadViewIfNeeded()
        let webView = try XCTUnwrap(controller.webView)
        var title: String?
        for _ in 0..<150 where title != "cached shell" {
            title = try? await webView.evaluateJavaScript("document.title") as? String
            if title != "cached shell" { try await Task.sleep(nanoseconds: 100_000_000) }
        }
        XCTAssertEqual(title, "cached shell")
        XCTAssertEqual(webView.url, OfflinePageAddress.home)
        let ran = try await webView.evaluateJavaScript("document.documentElement.dataset.ran") as? String
        XCTAssertEqual(ran, "yes")
    }

    @MainActor
    func testTheShellShowsNoCachedPageWhenNoTripsAreSaved() async throws {
        let server = URL(string: "https://127.0.0.1:\(Self.closedPort())")!
        try savePages(for: server)
        let before = (ShellViewController.serverURL, ShellViewController.gate)
        ShellViewController.serverURL = server
        ShellViewController.gate = gate
        defer { (ShellViewController.serverURL, ShellViewController.gate) = before }
        let controller = ShellViewController()
        controller.loadViewIfNeeded()
        let webView = try XCTUnwrap(controller.webView)
        try await Task.sleep(nanoseconds: 4_000_000_000)
        XCTAssertNotEqual(webView.url?.scheme, OfflinePageAddress.scheme)
        let title = try? await webView.evaluateJavaScript("document.title") as? String
        XCTAssertNotEqual(title, "cached shell")
    }
}
