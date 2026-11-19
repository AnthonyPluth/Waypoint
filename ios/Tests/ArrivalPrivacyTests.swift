import XCTest
@testable import Waypoint

private final class ArrivalRecordingProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var recorded: [URLRequest] = []

    static var seen: [URLRequest] {
        lock.lock()
        defer { lock.unlock() }
        return recorded
    }

    static func reset() {
        lock.lock()
        recorded = []
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        lock.lock()
        recorded.append(request)
        lock.unlock()
        return false
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {}
    override func stopLoading() {}
}

/// #819's criterion: no location reaches the server. The place lookups here go to a fake geocoder (the real one is Apple's, and the Python
/// test holds that it is named in one file); what the test shows is that driving the whole feature, regions, events, authorization changes
/// and every purge, makes no request to the Waypoint server and none anywhere that carries a coordinate.
final class ArrivalPrivacyTests: XCTestCase {
    private var rig: ArrivalRig!

    override func setUp() {
        super.setUp()
        ArrivalRecordingProtocol.reset()
        URLProtocol.registerClass(ArrivalRecordingProtocol.self)
    }

    override func tearDown() {
        URLProtocol.unregisterClass(ArrivalRecordingProtocol.self)
        rig?.cleanUp()
        rig = nil
        super.tearDown()
    }

    private func carriesACoordinate(_ request: URLRequest) -> Bool {
        var haystack = request.url?.absoluteString ?? ""
        for (name, value) in request.allHTTPHeaderFields ?? [:] {
            haystack += " \(name) \(value)"
        }
        if let body = request.httpBody, let text = String(data: body, encoding: .utf8) {
            haystack += " " + text
        }
        let points = [ArrivalFixtures.lot, ArrivalFixtures.inn, ArrivalFixtures.counter]
        let numbers = points.flatMap { [String($0.latitude), String($0.longitude)] }
        return numbers.contains { haystack.contains($0) }
    }

    func testRegionEventsAuthorizationChangesAndPurgesSendNothingToTheServerAndNoCoordinateAnywhere() async throws {
        let phone = ArrivalRig(authorization: .notDetermined)
        rig = phone
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot, "2 Rental Rd": ArrivalFixtures.counter, "3 Inn Ave": ArrivalFixtures.inn]
        let data = ArrivalFixtures.tripsJSON([ArrivalFixtures.parking(), ArrivalFixtures.rental(), ArrivalFixtures.hotel()])
        let sync = phone.makeSync(data: data)
        await phone.watch.foregrounded()
        await sync.sync()
        await sync.arrivalSettled()
        phone.locations.authorization = .whenInUse
        await phone.watch.handle(.authorizationChanged)
        phone.locations.authorization = .always
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds.count, 3)
        for id in [1, 2, 3] {
            phone.clock.date = ArrivalFixtures.moment(2026, 12, 1, 13)
            await phone.watch.handle(.entered(ArrivalWatch.regionId(id)))
        }
        XCTAssertEqual(phone.notifications.posted.count, 3)
        phone.locations.hasPreciseLocation = false
        await phone.watch.handle(.authorizationChanged)
        phone.locations.authorization = .denied
        await phone.watch.handle(.authorizationChanged)
        await sync.signedOut()
        await sync.arrivalSettled()

        let host = try XCTUnwrap(phone.home.host)
        let toTheServer = ArrivalRecordingProtocol.seen.filter { $0.url?.host == host }
        XCTAssertEqual(toTheServer.count, 0)
        XCTAssertEqual(ArrivalRecordingProtocol.seen.filter(carriesACoordinate).count, 0)
    }

    func testTheInAppCheckAndTheTapSendNothingToTheServerAndNoCoordinateAnywhere() async throws {
        let phone = ArrivalRig(authorization: .whenInUse, at: ArrivalFixtures.moment(2026, 12, 1, 13))
        rig = phone
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot, "2 Rental Rd": ArrivalFixtures.counter, "3 Inn Ave": ArrivalFixtures.inn]
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.rental(), ArrivalFixtures.hotel()])
        await phone.watch.saved(server: phone.home)
        let pending = PendingArrival()
        let bridge = OfflineBridge(store: phone.store, sync: phone.makeSync(), settings: OfflineSettings(defaults: phone.defaults), pending: pending, here: phone.here)
        ArrivalRecordingProtocol.reset()

        phone.fix.point = ArrivalFixtures.lot
        let made = ArrivalNotice(ArrivalPlace(segmentId: 1, tripId: 7, kind: .parking, latitude: ArrivalFixtures.lot.latitude,
                                              longitude: ArrivalFixtures.lot.longitude, radius: 250,
                                              opens: ArrivalFixtures.moment(2026, 12, 1, 7), closes: ArrivalFixtures.moment(2026, 12, 5, 18)))
        let center = NotificationCenter()
        ArrivalTap.respond(identifier: made.id, userInfo: made.content().userInfo, pending: pending, center: center)
        let atTheBooking = try await bridge.answer(["type": "arrivalHere"], server: phone.home)
        let tapped = try await bridge.answer(["type": "pendingArrival"], server: phone.home)
        await phone.here.backgrounded()

        for reply in [atTheBooking, tapped] {
            XCTAssertEqual(Set(reply.keys), ["version", "segmentId", "tripId"])
            let text = String(decoding: try JSONSerialization.data(withJSONObject: reply), as: UTF8.self)
            for number in [ArrivalFixtures.lot, ArrivalFixtures.inn, ArrivalFixtures.counter].flatMap({ [String($0.latitude), String($0.longitude)] }) {
                XCTAssertFalse(text.contains(number), number)
            }
        }
        XCTAssertEqual(atTheBooking["segmentId"] as? Int, 1)
        XCTAssertEqual(tapped["tripId"] as? Int, 7)
        let host = try XCTUnwrap(phone.home.host)
        XCTAssertEqual(ArrivalRecordingProtocol.seen.filter { $0.url?.host == host }.count, 0)
        XCTAssertEqual(ArrivalRecordingProtocol.seen.filter(carriesACoordinate).count, 0)
    }

    func testTheNotificationAndTheArrivalFileCarryNoCoordinateOutsideTheFile() async throws {
        let phone = ArrivalRig()
        rig = phone
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot]
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        phone.clock.date = ArrivalFixtures.moment(2026, 12, 1, 8)
        await phone.watch.handle(.entered("arrival-1"))
        let notice = try XCTUnwrap(phone.notifications.posted.first)
        let content = notice.content()
        let visible = [notice.title, notice.body, content.title, content.body, "\(content.userInfo)"].joined(separator: " ")
        for coordinate in [String(ArrivalFixtures.lot.latitude), String(ArrivalFixtures.lot.longitude), "Main St", "ABC123"] {
            XCTAssertFalse(visible.contains(coordinate), coordinate)
        }
    }

    func testTheRecorderSeesARequest() async {
        var request = URLRequest(url: URL(string: "https://recorder-check.invalid/probe")!)
        request.timeoutInterval = 2
        _ = try? await URLSession.shared.data(for: request)
        XCTAssertTrue(ArrivalRecordingProtocol.seen.contains { $0.url?.host == "recorder-check.invalid" })
    }
}
