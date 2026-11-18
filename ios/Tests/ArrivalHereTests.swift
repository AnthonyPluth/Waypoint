import XCTest
@testable import Waypoint

final class ArrivalHereTests: XCTestCase {
    private var rig: ArrivalRig!

    override func tearDown() {
        rig?.cleanUp()
        rig = nil
        super.tearDown()
    }

    private let afternoon = ArrivalFixtures.moment(2026, 12, 1, 13)

    private func nearBy(_ point: PlacePoint, north metres: Double) -> PlacePoint {
        PlacePoint(latitude: point.latitude + metres / 111_195, longitude: point.longitude)
    }

    /// A phone with While Using, the three kinds saved and their places found, at 13:00 on the first day.
    private func saved(_ authorization: ArrivalAuthorization = .whenInUse) async -> ArrivalRig {
        let phone = ArrivalRig(authorization: authorization, at: afternoon)
        rig = phone
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot, "2 Rental Rd": ArrivalFixtures.counter, "3 Inn Ave": ArrivalFixtures.inn]
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.rental(), ArrivalFixtures.hotel()])
        await phone.watch.saved(server: phone.home)
        return phone
    }

    private func snapshot(_ root: URL) -> [String: Data] {
        var found: [String: Data] = [:]
        let walker = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey])
        while let url = walker?.nextObject() as? URL {
            if (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true {
                found[url.path.replacingOccurrences(of: root.path, with: "")] = try? Data(contentsOf: url)
            }
        }
        return found
    }

    // MARK: The rules

    func testDistanceIsTheGreatCircleInMetres() {
        let there = nearBy(ArrivalFixtures.lot, north: 100)
        XCTAssertEqual(ArrivalHereRules.metres(from: ArrivalFixtures.lot, to: there), 100, accuracy: 1)
        XCTAssertEqual(ArrivalHereRules.metres(from: ArrivalFixtures.lot, to: ArrivalFixtures.lot), 0, accuracy: 0.001)
        XCTAssertEqual(ArrivalHereRules.metres(from: PlacePoint(latitude: 0, longitude: 0), to: PlacePoint(latitude: 0, longitude: 1)), 111_195, accuracy: 100)
    }

    func testTheBookingWhoseWindowOpenedLastWinsAndTiesGoToTheHigherId() {
        let opens = ArrivalFixtures.moment(2026, 12, 1, 7)
        let closes = ArrivalFixtures.moment(2026, 12, 5, 18)
        func place(_ id: Int, _ start: Date, radius: Double = 250) -> ArrivalPlace {
            ArrivalPlace(segmentId: id, tripId: 7, kind: .parking, latitude: ArrivalFixtures.lot.latitude, longitude: ArrivalFixtures.lot.longitude,
                         radius: radius, opens: start, closes: closes)
        }
        let later = ArrivalFixtures.moment(2026, 12, 1, 12)
        let chosen = ArrivalHereRules.place(among: [place(1, opens), place(2, later), place(3, opens)], at: ArrivalFixtures.lot, now: afternoon)
        XCTAssertEqual(chosen?.segmentId, 2)
        let tied = ArrivalHereRules.place(among: [place(4, opens), place(9, opens)], at: ArrivalFixtures.lot, now: afternoon)
        XCTAssertEqual(tied?.segmentId, 9)
        XCTAssertNil(ArrivalHereRules.place(among: [place(1, opens, radius: 10)], at: nearBy(ArrivalFixtures.lot, north: 50), now: afternoon))
        XCTAssertNil(ArrivalHereRules.place(among: [place(1, later)], at: ArrivalFixtures.lot, now: ArrivalFixtures.moment(2026, 12, 1, 11)))
        XCTAssertNil(ArrivalHereRules.place(among: [place(1, opens)], at: ArrivalFixtures.lot, now: closes))
    }

    // MARK: The answer

    func testAnswersWithTheBookingWhoseCircleHoldsThePhoneAndOnlyItsIds() async {
        let phone = await saved()
        phone.fix.point = nearBy(ArrivalFixtures.lot, north: 60)
        let found = await phone.here.answer(server: phone.home)
        XCTAssertEqual(found, ArrivalHereAnswer(segmentId: 1, tripId: 7))
        XCTAssertEqual(phone.fix.requests, 1)
    }

    func testEachKindIsFoundByItsOwnCircle() async {
        let phone = await saved()
        for (point, id) in [(ArrivalFixtures.counter, 2), (ArrivalFixtures.inn, 3)] {
            await phone.here.backgrounded()
            phone.fix.point = nearBy(point, north: 40)
            let found = await phone.here.answer(server: phone.home)
            XCTAssertEqual(found?.segmentId, id)
        }
    }

    func testAnswersNothingOutsideEveryCircle() async {
        let phone = await saved()
        phone.fix.point = nearBy(ArrivalFixtures.lot, north: 1_100)
        let found = await phone.here.answer(server: phone.home)
        XCTAssertNil(found)
        XCTAssertEqual(phone.fix.requests, 1)
    }

    func testAnswersNothingAndAsksForNoLocationWhileNoWindowIsOpen() async {
        let phone = await saved()
        phone.clock.date = ArrivalFixtures.moment(2026, 11, 30, 12)
        phone.fix.point = ArrivalFixtures.lot
        let found = await phone.here.answer(server: phone.home)
        XCTAssertNil(found)
        XCTAssertEqual(phone.fix.requests, 0)
    }

    func testAnswersNothingForAWindowThatHasClosed() async {
        let phone = await saved()
        phone.clock.date = ArrivalFixtures.moment(2026, 12, 1, 15)
        phone.fix.point = ArrivalFixtures.counter
        let found = await phone.here.answer(server: phone.home)
        XCTAssertNil(found)
    }

    func testWhenTwoCirclesHoldThePhoneTheWindowThatOpenedLastWins() async {
        let phone = ArrivalRig(authorization: .whenInUse, at: afternoon)
        rig = phone
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot, "3 Inn Ave": ArrivalFixtures.lot]
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.hotel()])
        await phone.watch.saved(server: phone.home)
        phone.fix.point = ArrivalFixtures.lot
        let found = await phone.here.answer(server: phone.home)
        XCTAssertEqual(found?.segmentId, 3)
    }

    // MARK: Once for each time the app comes forward

    func testOneRequestServesEveryAskUntilTheAppGoesToTheBackground() async {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        let first = await phone.here.answer(server: phone.home)
        let second = await phone.here.answer(server: phone.home)
        XCTAssertEqual(first, second)
        XCTAssertEqual(phone.fix.requests, 1)
        await phone.here.backgrounded()
        phone.fix.point = ArrivalFixtures.counter
        let third = await phone.here.answer(server: phone.home)
        XCTAssertEqual(third?.segmentId, 2)
        XCTAssertEqual(phone.fix.requests, 2)
    }

    func testACachedAnswerEndsWhenSavingIsSwitchedOffInTheSameForegroundSession() async {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        let first = await phone.here.answer(server: phone.home)
        XCTAssertEqual(first?.segmentId, 1)
        OfflineSettings(defaults: phone.defaults).set(false)
        let second = await phone.here.answer(server: phone.home)
        XCTAssertNil(second)
        XCTAssertEqual(phone.fix.requests, 1)
    }

    func testACachedAnswerEndsWhenTheSavedTripsArePurged() async throws {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        let first = await phone.here.answer(server: phone.home)
        XCTAssertEqual(first?.segmentId, 1)
        try phone.store.purge(server: phone.home)
        let second = await phone.here.answer(server: phone.home)
        XCTAssertNil(second)
    }

    func testACachedAnswerEndsWhenThePhoneCanNoLongerBeAsked() async {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        _ = await phone.here.answer(server: phone.home)
        phone.fix.isAllowed = false
        let second = await phone.here.answer(server: phone.home)
        XCTAssertNil(second)
    }

    func testAnAskBeforeThePrerequisitesAreReadyIsNotCachedForTheSession() async {
        let phone = ArrivalRig(authorization: .whenInUse, at: afternoon)
        rig = phone
        phone.fix.point = ArrivalFixtures.lot
        let nothingSaved = await phone.here.answer(server: phone.home)
        XCTAssertNil(nothingSaved)
        phone.fix.isAllowed = false
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot]
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        let noPermission = await phone.here.answer(server: phone.home)
        XCTAssertNil(noPermission)
        XCTAssertEqual(phone.fix.requests, 0)
        phone.fix.isAllowed = true
        let ready = await phone.here.answer(server: phone.home)
        XCTAssertEqual(ready?.segmentId, 1)
        XCTAssertEqual(phone.fix.requests, 1)
    }

    func testACompletedCheckThatFoundNobodyStaysForTheSession() async {
        let phone = await saved()
        phone.fix.point = nearBy(ArrivalFixtures.lot, north: 1_100)
        _ = await phone.here.answer(server: phone.home)
        _ = await phone.here.answer(server: phone.home)
        XCTAssertEqual(phone.fix.requests, 1)
    }

    func testAnswersAgainForAnotherServer() async {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        _ = await phone.here.answer(server: phone.home)
        let other = URL(string: "https://other.example.com")!
        let found = await phone.here.answer(server: other)
        XCTAssertNil(found)
    }

    // MARK: What stops it

    func testAsksForNoLocationWithoutPermissionPreciseLocationOrSaving() async {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        phone.fix.isAllowed = false
        let refused = await phone.here.answer(server: phone.home)
        XCTAssertNil(refused)
        phone.fix.isAllowed = true
        await phone.here.backgrounded()
        OfflineSettings(defaults: phone.defaults).set(false)
        let off = await phone.here.answer(server: phone.home)
        XCTAssertNil(off)
        XCTAssertEqual(phone.fix.requests, 0)
    }

    func testAnswersNothingAndReadsNothingWhileTheSavedTripsAreUnreadable() async {
        let phone = await saved()
        phone.fix.point = ArrivalFixtures.lot
        phone.protectedData.value = false
        let found = await phone.here.answer(server: phone.home)
        XCTAssertNil(found)
        XCTAssertEqual(phone.fix.requests, 0)
    }

    func testAnswersNothingWhenThereIsNoFix() async {
        let phone = await saved()
        phone.fix.point = nil
        let found = await phone.here.answer(server: phone.home)
        XCTAssertNil(found)
        XCTAssertEqual(phone.fix.requests, 1)
    }

    func testAnswersNothingWithNothingSaved() async {
        let phone = ArrivalRig(authorization: .whenInUse, at: afternoon)
        rig = phone
        phone.fix.point = ArrivalFixtures.lot
        let found = await phone.here.answer(server: phone.home)
        XCTAssertNil(found)
        XCTAssertEqual(phone.fix.requests, 0)
    }

    // MARK: Nothing is kept

    func testTheFixIsNotWrittenAnywhere() async throws {
        let phone = await saved()
        let before = snapshot(phone.root)
        XCTAssertFalse(before.isEmpty)
        phone.fix.point = nearBy(ArrivalFixtures.lot, north: 37)
        _ = await phone.here.answer(server: phone.home)
        await phone.here.backgrounded()
        let after = snapshot(phone.root)
        XCTAssertEqual(before, after)
        let marker = String(nearBy(ArrivalFixtures.lot, north: 37).latitude)
        for (_, data) in after {
            XCTAssertFalse(String(decoding: data, as: UTF8.self).contains(marker))
        }
    }
}
