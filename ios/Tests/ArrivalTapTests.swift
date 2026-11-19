import UserNotifications
import XCTest
@testable import Waypoint

private final class TapCount: @unchecked Sendable {
    private(set) var value = 0

    func raise() {
        value += 1
    }
}

final class ArrivalTapTests: XCTestCase {
    private func notice(_ segmentId: Int = 5, _ tripId: Int = 7, kind: ArrivalKind = .parking) -> ArrivalNotice {
        ArrivalNotice(ArrivalPlace(segmentId: segmentId, tripId: tripId, kind: kind, latitude: 39.7, longitude: -104.9, radius: 250,
                                   opens: ArrivalFixtures.moment(2026, 12, 1, 7), closes: ArrivalFixtures.moment(2026, 12, 5, 18)))
    }

    // MARK: What a tap hands over

    func testATapOnTheNotificationNamesTheBookingByItsTwoIds() {
        let made = notice()
        let target = ArrivalTap.target(identifier: made.id, userInfo: made.content().userInfo)
        XCTAssertEqual(target, PendingArrival.Target(segmentId: 5, tripId: 7))
    }

    func testOnlyArrivalNotificationsWithMatchingIdsAreTaken() {
        let info: [AnyHashable: Any] = ["segmentId": 5, "tripId": 7]
        XCTAssertNil(ArrivalTap.target(identifier: "reminder-5", userInfo: info))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-6", userInfo: info))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-x", userInfo: info))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-5", userInfo: ["segmentId": "5", "tripId": 7]))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-5", userInfo: ["segmentId": 5]))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-5", userInfo: ["segmentId": 5, "tripId": 0]))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-0", userInfo: ["segmentId": 0, "tripId": 7]))
        XCTAssertNil(ArrivalTap.target(identifier: "arrival-5", userInfo: [:]))
    }

    func testATapHoldsTheIdsAndTellsTheShellAndNothingElse() {
        let pending = PendingArrival()
        let center = NotificationCenter()
        let told = TapCount()
        let observer = center.addObserver(forName: .openArrival, object: nil, queue: nil) { _ in told.raise() }
        defer { center.removeObserver(observer) }
        let made = notice(5, 7, kind: .rentalPickup)
        XCTAssertTrue(ArrivalTap.respond(identifier: made.id, userInfo: made.content().userInfo, pending: pending, center: center))
        XCTAssertEqual(told.value, 1)
        XCTAssertTrue(pending.isWaiting())
        XCTAssertEqual(pending.take(), PendingArrival.Target(segmentId: 5, tripId: 7))
    }

    func testATapOnAnythingElseHoldsNothingAndTellsNoOne() {
        let pending = PendingArrival()
        let center = NotificationCenter()
        let told = TapCount()
        let observer = center.addObserver(forName: .openArrival, object: nil, queue: nil) { _ in told.raise() }
        defer { center.removeObserver(observer) }
        XCTAssertFalse(ArrivalTap.respond(identifier: "something-else", userInfo: ["segmentId": 5, "tripId": 7], pending: pending, center: center))
        XCTAssertEqual(told.value, 0)
        XCTAssertFalse(pending.isWaiting())
        XCTAssertNil(pending.take())
    }

    func testTheNotificationItselfCarriesOnlyTheTwoIds() {
        let content = notice().content()
        XCTAssertEqual(Set(content.userInfo.keys.compactMap { $0 as? String }), ["segmentId", "tripId"])
        XCTAssertNil(content.sound)
    }

    // MARK: The pending arrival

    func testItIsAnsweredOnce() {
        let pending = PendingArrival()
        let start = ArrivalFixtures.moment(2026, 12, 1, 12)
        pending.hold(segmentId: 5, tripId: 7, now: start)
        XCTAssertEqual(pending.take(now: start.addingTimeInterval(5)), PendingArrival.Target(segmentId: 5, tripId: 7))
        XCTAssertNil(pending.take(now: start.addingTimeInterval(6)))
        XCTAssertFalse(pending.isWaiting(now: start.addingTimeInterval(6)))
    }

    func testItIsForgottenAfterTwoMinutes() {
        let pending = PendingArrival()
        let start = ArrivalFixtures.moment(2026, 12, 1, 12)
        pending.hold(segmentId: 5, tripId: 7, now: start)
        XCTAssertTrue(pending.isWaiting(now: start.addingTimeInterval(PendingArrival.lifetime)))
        XCTAssertFalse(pending.isWaiting(now: start.addingTimeInterval(PendingArrival.lifetime + 1)))
        XCTAssertNil(pending.take(now: start.addingTimeInterval(PendingArrival.lifetime + 1)))
        XCTAssertNil(pending.take(now: start))
    }

    func testTheNewestTapReplacesTheOlderOne() {
        let pending = PendingArrival()
        pending.hold(segmentId: 5, tripId: 7)
        pending.hold(segmentId: 6, tripId: 7)
        XCTAssertEqual(pending.take()?.segmentId, 6)
    }

    func testIdsThatAreNotPositiveAreNotHeld() {
        let pending = PendingArrival()
        pending.hold(segmentId: 0, tripId: 7)
        pending.hold(segmentId: 5, tripId: -1)
        XCTAssertNil(pending.take())
    }

    func testClearForgetsIt() {
        let pending = PendingArrival()
        pending.hold(segmentId: 5, tripId: 7)
        pending.clear()
        XCTAssertNil(pending.take())
    }
}
