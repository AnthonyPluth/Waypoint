import XCTest
@testable import Waypoint

private final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [String] = []

    func add(_ item: String) {
        lock.lock()
        items.append(item)
        lock.unlock()
    }

    var all: [String] {
        lock.lock()
        defer { lock.unlock() }
        return items
    }
}

private final class FakeServerAPI: ServerAPI, @unchecked Sendable {
    static let noConnection = ServerError.offline("The Internet connection appears to be offline.")
    static let sample = WebCookie(name: "waypoint_session", value: "session-value", maxAge: 3600, secure: true)

    let cookieRequests = Recorder()
    let refreshRequests = Recorder()
    var cookie: @Sendable (String) async throws -> WebCookie = { _ in throw FakeServerAPI.noConnection }
    var endpointsFailure: Error?
    var refreshFailure: Error?

    func endpoints(_ server: URL) async throws -> Endpoints {
        if let endpointsFailure { throw endpointsFailure }
        let base = server.absoluteString
        return Endpoints(issuer: base, authorizationEndpoint: URL(string: base + "/oauth/authorize")!,
                         tokenEndpoint: URL(string: base + "/oauth/token")!, revocationEndpoint: URL(string: base + "/oauth/revoke")!)
    }

    func refresh(_ refreshToken: String, endpoints: Endpoints) async throws -> Tokens {
        refreshRequests.add(refreshToken)
        if let refreshFailure { throw refreshFailure }
        return Tokens(accessToken: "wpa_renewed", refreshToken: "wpr_renewed", expiresAt: Date().addingTimeInterval(3600))
    }

    func webCookie(_ server: URL, accessToken: String) async throws -> WebCookie {
        cookieRequests.add(accessToken)
        return try await cookie(accessToken)
    }

    func revoke(_ refreshToken: String, endpoints: Endpoints) async -> Bool { true }
}

private final class Flag: @unchecked Sendable {
    private let lock = NSLock()
    private var raised = false

    func raise() {
        lock.lock()
        raised = true
        lock.unlock()
    }

    var isRaised: Bool {
        lock.lock()
        defer { lock.unlock() }
        return raised
    }
}

final class WebLaunchTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!
    private var suite: String!
    private var store: OfflineStore!
    private var pages: OfflinePages!
    private var gate: OfflineGate!
    private var api: FakeServerAPI!
    private var installed: Recorder!
    private var sessions: [ServerSession] = []
    private let home = URL(string: "https://waypoint.example.com")!
    private let longPatience: UInt64 = 30_000_000_000

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("web-launch-\(UUID().uuidString)", isDirectory: true)
        suite = "web-launch-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        store = TripFixtures.store(at: root.appendingPathComponent("trips"))
        pages = OfflinePages(root: root.appendingPathComponent("pages"))
        gate = OfflineGate(store: store, pages: pages)
        api = FakeServerAPI()
        installed = Recorder()
        sessions = []
    }

    override func tearDown() {
        let finishing = sessions
        let done = expectation(description: "pending revocations settled")
        Task {
            for session in finishing { await session.retryPendingRevocations() }
            done.fulfill()
        }
        wait(for: [done], timeout: 10)
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private func makeSession(tokens: Tokens? = nil) -> ServerSession {
        let held: Tokens? = tokens ?? Tokens(accessToken: "wpa_held", refreshToken: "wpr_held", expiresAt: Date().addingTimeInterval(3600))
        let recorder = installed!
        let session = ServerSession(
            offline: OfflineSync(store: store, settings: OfflineSettings(defaults: defaults), pages: pages, server: { [home] in home }, bearer: { nil }),
            api: api, restoring: (home, held), installCookie: { cookie, _ in recorder.add(cookie.value) })
        sessions.append(session)
        return session
    }

    private func saveTripsAndPage(for server: URL? = nil) throws {
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: server ?? home)
        try pages.save(["/": Data("<html><body>cached</body></html>".utf8)], build: "b1", for: server ?? home)
    }

    func testAColdLaunchWithNoConnectionOpensTheCachedPageWhenTripsAndAPageAreSaved() async throws {
        try saveTripsAndPage()
        let launch = await makeSession().launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .cachedPage(home))
        XCTAssertEqual(api.cookieRequests.all, ["wpa_held"])
        XCTAssertEqual(installed.all, [], "no cookie is installed for the cached page")
        XCTAssertNotNil(store.load(server: home), "the saved trips stay")
    }

    func testAColdLaunchWhoseTokenRenewalCannotReachTheServerOpensTheCachedPage() async throws {
        try saveTripsAndPage()
        api.endpointsFailure = FakeServerAPI.noConnection
        let expired = Tokens(accessToken: "wpa_old", refreshToken: "wpr_old", expiresAt: Date().addingTimeInterval(-60))
        let launch = await makeSession(tokens: expired).launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .cachedPage(home))
        XCTAssertEqual(api.cookieRequests.all, [], "no cookie request goes out without a token")
        XCTAssertEqual(api.refreshRequests.all, [])
        XCTAssertEqual(installed.all, [])
    }

    func testAColdLaunchWithNoConnectionShowsTheErrorWhenNoTripsAreSaved() async throws {
        try pages.save(["/": Data("<html></html>".utf8)], build: "b1", for: home)
        let launch = await makeSession().launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .failed(FakeServerAPI.noConnection.localizedDescription))
        XCTAssertFalse(pages.hasPage(for: home), "a page with no trips is deleted, as the gate always does")
        XCTAssertEqual(installed.all, [])
    }

    func testAColdLaunchWithNoConnectionShowsTheErrorWhenTripsAreSavedButNoPage() async throws {
        try store.save(TripFixtures.reply(["Lisbon"]), version: 1, for: home)
        let launch = await makeSession().launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .failed(FakeServerAPI.noConnection.localizedDescription))
    }

    func testTheCachedPageIsNotOpenedForTripsSavedForAnotherServer() async throws {
        try saveTripsAndPage(for: URL(string: "https://other.example.com")!)
        let launch = await makeSession().launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .failed(FakeServerAPI.noConnection.localizedDescription))
    }

    func testA401FromTheCookieRequestPurgesTheSavedTripsAndSignsOut() async throws {
        try saveTripsAndPage()
        api.cookie = { _ in throw ServerError.signedOut }
        let session = makeSession()
        let launch = await session.launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .signedOut)
        XCTAssertNil(store.load(server: home))
        XCTAssertFalse(pages.hasPage(for: home))
        let server = await session.server
        XCTAssertNil(server)
        XCTAssertEqual(installed.all, [])
    }

    func testARefusedSignInRenewalPurgesTheSavedTripsAndSignsOut() async throws {
        try saveTripsAndPage()
        api.refreshFailure = ServerError.signedOut
        let expired = Tokens(accessToken: "wpa_old", refreshToken: "wpr_old", expiresAt: Date().addingTimeInterval(-60))
        let launch = await makeSession(tokens: expired).launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .signedOut)
        XCTAssertNil(store.load(server: home))
        XCTAssertEqual(api.cookieRequests.all, [])
    }

    func testASlowCookieRequestOpensTheCachedPageOnceThePatienceRunsOut() async throws {
        try saveTripsAndPage()
        api.cookie = { _ in
            try await Task.sleep(nanoseconds: 20_000_000_000)
            return FakeServerAPI.sample
        }
        let started = Date()
        let launch = await makeSession().launchWebView(gate: gate, patience: 100_000_000)
        XCTAssertEqual(launch, .cachedPage(home))
        XCTAssertLessThan(Date().timeIntervalSince(started), 10)
        XCTAssertEqual(installed.all, [])
    }

    func testASlowCookieRequestIsWaitedForWhenNothingIsSaved() async throws {
        api.cookie = { _ in
            try await Task.sleep(nanoseconds: 300_000_000)
            return FakeServerAPI.sample
        }
        let launch = await makeSession().launchWebView(gate: gate, patience: 50_000_000)
        XCTAssertEqual(launch, .server(home))
        XCTAssertEqual(installed.all, ["session-value"])
    }

    func testAnAnsweringServerOpensTheServerWithItsCookie() async throws {
        try saveTripsAndPage()
        api.cookie = { _ in FakeServerAPI.sample }
        let launch = await makeSession().launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(launch, .server(home))
        XCTAssertEqual(installed.all, ["session-value"])
    }

    func testAFailureThatIsNotALostConnectionShowsTheErrorEvenWithSavedTrips() async throws {
        try saveTripsAndPage()
        for failure in [ServerError.notWaypoint, ServerError.notReachable("certificate"), ServerError.needsPublicURL] {
            api.cookie = { _ in throw failure }
            let launch = await makeSession().launchWebView(gate: gate, patience: longPatience)
            XCTAssertEqual(launch, .failed(failure.localizedDescription), "\(failure)")
        }
        XCTAssertNotNil(store.load(server: home))
    }

    func testReturningToTheServerGetsTheWebCookieFirst() async throws {
        try saveTripsAndPage()
        let session = makeSession()
        let first = await session.launchWebView(gate: gate, patience: longPatience)
        XCTAssertEqual(first, .cachedPage(home))
        api.cookie = { _ in FakeServerAPI.sample }
        let ready = await session.renewForReturn()
        XCTAssertTrue(ready)
        XCTAssertEqual(installed.all, ["session-value"])
        let again = await session.renewForReturn()
        XCTAssertTrue(again)
        XCTAssertEqual(installed.all, ["session-value"], "a fresh cookie is not asked for twice")
    }

    func testReturningToTheServerWaitsWhileItStillCannotBeReached() async throws {
        try saveTripsAndPage()
        let session = makeSession()
        _ = await session.launchWebView(gate: gate, patience: longPatience)
        let ready = await session.renewForReturn()
        XCTAssertFalse(ready)
        XCTAssertEqual(installed.all, [])
        XCTAssertNotNil(store.load(server: home))
    }

    func testReturningToTheServerWithAnEndedSignInTellsTheApp() async throws {
        try saveTripsAndPage()
        let session = makeSession()
        _ = await session.launchWebView(gate: gate, patience: longPatience)
        api.cookie = { _ in throw ServerError.signedOut }
        let told = Flag()
        let observer = NotificationCenter.default.addObserver(forName: .webViewUnauthorized, object: nil, queue: nil) { _ in told.raise() }
        defer { NotificationCenter.default.removeObserver(observer) }
        let ready = await session.renewForReturn()
        XCTAssertFalse(ready)
        XCTAssertTrue(told.isRaised)
    }
}

final class WebCookieReplyTests: XCTestCase {
    private let body = Data(#"{"name":"waypoint_session","value":"v","max_age":3600,"secure":true}"#.utf8)

    func testA200WithACookieIsTaken() throws {
        let cookie = try ServerClient.cookie(from: body, status: 200)
        XCTAssertEqual(cookie.name, "waypoint_session")
        XCTAssertEqual(cookie.maxAge, 3600)
    }

    func testA401And403MeanTheSignInEnded() {
        for status in [401, 403] {
            XCTAssertThrowsError(try ServerClient.cookie(from: Data(), status: status)) { error in
                guard case ServerError.signedOut = error else { return XCTFail("\(status): \(error)") }
            }
        }
    }

    func testAnythingElseIsNotAWaypointAnswer() {
        for (data, status) in [(body, 500), (body, 502), (Data("nope".utf8), 200)] {
            XCTAssertThrowsError(try ServerClient.cookie(from: data, status: status)) { error in
                guard case ServerError.notWaypoint = error else { return XCTFail("\(status): \(error)") }
            }
        }
    }
}

final class ServerFailureKindTests: XCTestCase {
    func testALostConnectionIsOffline() {
        for code in [URLError.Code.notConnectedToInternet, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed, .timedOut, .networkConnectionLost] {
            guard case ServerError.offline = ServerClient.failure(for: URLError(code)) else { return XCTFail("\(code)") }
        }
    }

    func testOtherFailuresAreNotOffline() {
        for code in [URLError.Code.cancelled, .serverCertificateUntrusted, .secureConnectionFailed, .badServerResponse] {
            guard case ServerError.notReachable = ServerClient.failure(for: URLError(code)) else { return XCTFail("\(code)") }
        }
    }

    func testTheMessageIsTheSameEitherWay() {
        XCTAssertEqual(ServerError.offline("x").localizedDescription, ServerError.notReachable("x").localizedDescription)
    }
}
