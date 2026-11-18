import UserNotifications
import XCTest
@testable import Waypoint

final class ArrivalWatchTests: XCTestCase {
    private var rig: ArrivalRig!

    override func tearDown() {
        rig?.cleanUp()
        rig = nil
        super.tearDown()
    }

    private func makeRig(_ authorization: ArrivalAuthorization = .always, at start: Date = ArrivalFixtures.moment(2026, 11, 30, 12)) -> ArrivalRig {
        let made = ArrivalRig(authorization: authorization, at: start)
        rig = made
        return made
    }

    private func answers(_ geocoder: FakeArrivalGeocoder) {
        geocoder.answers = ["1 Main St": ArrivalFixtures.lot, "2 Rental Rd": ArrivalFixtures.counter, "3 Inn Ave": ArrivalFixtures.inn]
    }

    /// A phone with the three kinds saved and watched.
    private func watching(_ authorization: ArrivalAuthorization = .always) async -> ArrivalRig {
        let phone = makeRig(authorization)
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.rental(), ArrivalFixtures.hotel()])
        await phone.watch.saved(server: phone.home)
        return phone
    }

    private func enter(_ phone: ArrivalRig, _ id: Int, at date: Date) async {
        phone.clock.date = date
        await phone.watch.handle(.entered(ArrivalWatch.regionId(id)))
    }

    // MARK: Which places are watched

    func testTheThreeKindsAreWatchedWithTheirCirclesAndOnlyArrivalIds() async {
        let phone = await watching()
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1", "arrival-2", "arrival-3"])
        XCTAssertEqual(phone.locations.radii["arrival-1"], 250)
        XCTAssertEqual(phone.locations.radii["arrival-2"], 300)
        XCTAssertEqual(phone.locations.radii["arrival-3"], 200)
        XCTAssertEqual(phone.locations.regions["arrival-1"], ArrivalFixtures.lot)
        XCTAssertTrue(phone.locations.monitoredIds.allSatisfy { $0.hasPrefix("arrival-") && Int($0.dropFirst(8)) != nil })
    }

    func testAtMostFifteenAreWatchedSoonestWindowFirst() async {
        let phone = makeRig()
        var segments: [[String: Any]] = []
        for id in 1...17 {
            let day = String(format: "2026-12-%02d", 18 - id)
            segments.append(ArrivalFixtures.segment(id, "parking", start: "\(day)T09:00", end: "2026-12-30T18:00", address: "\(id) Main St"))
            phone.geocoder.answers["\(id) Main St"] = PlacePoint(latitude: 39.0 + Double(id) / 100, longitude: -104.0)
        }
        phone.save(segments)
        await phone.watch.saved(server: phone.home)
        let expected = (3...17).map { ArrivalWatch.regionId($0) }.sorted()
        XCTAssertEqual(phone.locations.monitoredIds, expected)
        XCTAssertEqual(ArrivalWatch.maxRegions, 15)
    }

    func testTheRegionsAreRebuiltAfterEachSave() async {
        let phone = await watching()
        phone.save([ArrivalFixtures.hotel()])
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-3"])
        phone.save([ArrivalFixtures.hotel(), ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1", "arrival-3"])
    }

    func testTheRegionsAreRebuiltWhenTheAppBecomesActive() async {
        let phone = await watching()
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.activated()
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
    }

    func testTheRegionsAreRebuiltOnEachRegionEvent() async {
        let phone = await watching()
        phone.clock.date = ArrivalFixtures.moment(2026, 12, 5, 19)
        await phone.watch.handle(.entered("arrival-3"))
        XCTAssertEqual(phone.locations.monitoredIds, [])
    }

    func testTheRegionsAreRebuiltOnEachAuthorizationChange() async {
        let phone = makeRig(.whenInUse)
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.monitoredIds, [])
        phone.locations.authorization = .always
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
    }

    func testNothingIsWatchedWithWhileUsingOrWithoutPreciseLocation() async {
        let whileUsing = await watching(.whenInUse)
        XCTAssertEqual(whileUsing.locations.monitoredIds, [])
        whileUsing.cleanUp()
        let phone = makeRig(.always)
        phone.locations.hasPreciseLocation = false
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.monitoredIds, [])
    }

    func testTheArrivalFileHoldsOnlyIdsKindWindowCentreAndRadius() async throws {
        let phone = makeRig()
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.saved(server: phone.home)
        let text = try XCTUnwrap(phone.arrivalText)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        let watched = try XCTUnwrap(object["watched"] as? [[String: Any]])
        XCTAssertEqual(watched.count, 1)
        XCTAssertEqual(Set(watched[0].keys), ["place"])
        let place = try XCTUnwrap(watched[0]["place"] as? [String: Any])
        XCTAssertEqual(Set(place.keys), ["segmentId", "tripId", "kind", "latitude", "longitude", "radius", "opens", "closes"])
        for secret in ["Main St", "ABC123", "555-0100", "Denver"] {
            XCTAssertFalse(text.contains(secret), secret)
        }
        let value = try FileManager.default.attributesOfItem(atPath: phone.arrivalFile.path)[.protectionKey] as? FileProtectionType
        if let value { XCTAssertEqual(value, FileProtectionType.completeUntilFirstUserAuthentication) }
    }

    func testASaveCarriesTheArrivalFileOverAndDropsTheWatchedPlacesOfATripNoLongerSaved() async throws {
        let phone = await watching()
        let before = try XCTUnwrap(phone.arrivalText)
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.rental(), ArrivalFixtures.hotel()])
        let after = try XCTUnwrap(phone.arrivalText)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        XCTAssertEqual(try decoder.decode(ArrivalFileContent.self, from: Data(after.utf8)),
                       try decoder.decode(ArrivalFileContent.self, from: Data(before.utf8)))
        try phone.store.save(Data(#"{"version":1,"trips":[]}"#.utf8), version: 1, for: phone.home)
        XCTAssertNil(phone.store.loadArrival(server: phone.home))
    }

    // MARK: The notification, window and frequency

    func testTheNotificationNamesTheKindOnly() {
        let window = (opens: Date(timeIntervalSince1970: 0), closes: Date(timeIntervalSince1970: 100))
        func notice(_ kind: ArrivalKind) -> ArrivalNotice {
            ArrivalNotice(ArrivalPlace(segmentId: 5, tripId: 7, kind: kind, latitude: 1, longitude: 2, radius: 250,
                                       opens: window.opens, closes: window.closes))
        }
        XCTAssertEqual(notice(.parking).title, "Your parking code is ready")
        XCTAssertEqual(notice(.parking).body, "You’re near your parking booking. Tap to show the QR code.")
        XCTAssertEqual(notice(.rentalPickup).title, "Your rental pickup is near")
        XCTAssertEqual(notice(.rentalPickup).body, "Tap to show your confirmation number.")
        XCTAssertEqual(notice(.hotel).title, "You’re near your hotel")
        XCTAssertEqual(notice(.hotel).body, "Tap to show your check-in details.")
        XCTAssertEqual(notice(.hotel).id, "arrival-5")
    }

    func testTheNotificationIsAlertsOnlyPassiveAndCarriesTwoIds() {
        let place = ArrivalPlace(segmentId: 5, tripId: 7, kind: .parking, latitude: 1, longitude: 2, radius: 250,
                                 opens: Date(timeIntervalSince1970: 0), closes: Date(timeIntervalSince1970: 100))
        let content = ArrivalNotice(place).content()
        XCTAssertNil(content.sound)
        XCTAssertNil(content.badge)
        XCTAssertEqual(content.interruptionLevel, .passive)
        XCTAssertEqual(content.userInfo["segmentId"] as? Int, 5)
        XCTAssertEqual(content.userInfo["tripId"] as? Int, 7)
        XCTAssertEqual(Set(content.userInfo.keys.compactMap { $0 as? String }), ["segmentId", "tripId"])
    }

    func testParkingNotifiesInsideItsWindowAndAgainAfterFourHours() async {
        let phone = await watching()
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 6, 59))
        XCTAssertEqual(phone.notifications.posted.count, 0)
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.posted.map(\.id), ["arrival-1"])
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 11, 59))
        XCTAssertEqual(phone.notifications.posted.count, 1)
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 12))
        XCTAssertEqual(phone.notifications.posted.count, 2)
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 5, 18, 1))
        XCTAssertEqual(phone.notifications.posted.count, 2)
    }

    func testARentalPickupNotifiesOnceInsideItsWindow() async {
        let phone = await watching()
        await enter(phone, 2, at: ArrivalFixtures.moment(2026, 12, 1, 7, 59))
        XCTAssertEqual(phone.notifications.posted.count, 0)
        await enter(phone, 2, at: ArrivalFixtures.moment(2026, 12, 1, 9))
        XCTAssertEqual(phone.notifications.posted.map(\.title), ["Your rental pickup is near"])
        await enter(phone, 2, at: ArrivalFixtures.moment(2026, 12, 1, 13))
        XCTAssertEqual(phone.notifications.posted.count, 1)
    }

    func testAHotelNotifiesOnceOnTheCheckInDayFromThreeHoursBefore() async {
        let phone = await watching()
        await enter(phone, 3, at: ArrivalFixtures.moment(2026, 12, 1, 11, 59))
        XCTAssertEqual(phone.notifications.posted.count, 0)
        await enter(phone, 3, at: ArrivalFixtures.moment(2026, 12, 1, 13))
        XCTAssertEqual(phone.notifications.posted.map(\.title), ["You’re near your hotel"])
        await enter(phone, 3, at: ArrivalFixtures.moment(2026, 12, 1, 20))
        XCTAssertEqual(phone.notifications.posted.count, 1)
        await enter(phone, 3, at: ArrivalFixtures.moment(2026, 12, 2, 1))
        XCTAssertEqual(phone.notifications.posted.count, 1)
    }

    func testNothingIsPostedForAnIdThatIsNotWatched() async {
        let phone = await watching()
        phone.clock.date = ArrivalFixtures.moment(2026, 12, 1, 9)
        await phone.watch.handle(.entered("arrival-99"))
        await phone.watch.handle(.entered("somewhere-1"))
        await phone.watch.handle(.entered("arrival-x"))
        XCTAssertEqual(phone.notifications.posted.count, 0)
    }

    func testTheFrequencyRuleIsKeptAcrossARebuild() async {
        let phone = await watching()
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        await phone.watch.saved(server: phone.home)
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 9))
        XCTAssertEqual(phone.notifications.posted.count, 1)
    }

    func testNotificationsOffStopsOnlyTheNotification() async {
        let phone = await watching()
        phone.notifications.allowed = false
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.posted.count, 0)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1", "arrival-2", "arrival-3"])
        phone.notifications.allowed = true
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8, 30))
        XCTAssertEqual(phone.notifications.posted.count, 1)
    }

    func testANotificationIsRemovedWhenItsWindowEnds() async {
        let phone = await watching()
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.current, ["arrival-1"])
        phone.clock.date = ArrivalFixtures.moment(2026, 12, 5, 18, 1)
        await phone.watch.activated()
        XCTAssertEqual(phone.notifications.current, [])
        XCTAssertEqual(phone.locations.monitoredIds, [])
    }

    // MARK: A wake-up while the phone is locked

    func testAWakeUpWhileLockedReadsTheArrivalFileAndNeverTheSavedTrips() async throws {
        let phone = await watching()
        phone.protectedData.value = false
        let folder = phone.root.appendingPathComponent(OfflineStore.folderName(for: phone.home), isDirectory: true)
        try FileManager.default.removeItem(at: folder.appendingPathComponent("trips.json"))
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.posted.map(\.id), ["arrival-1"])
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.path))
        XCTAssertNotNil(phone.store.loadArrival(server: phone.home))
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 5, 19))
        XCTAssertEqual(phone.notifications.current, [])
        XCTAssertEqual(phone.locations.monitoredIds, [])
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.path))
    }

    // MARK: The asks

    private func qualifyingPhone() -> ArrivalRig {
        let phone = makeRig(.notDetermined)
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking()])
        return phone
    }

    func testTheAsksAreMadeOnceEachInOrderAndAlwaysOnlyAfterWhileUsing() async {
        let phone = qualifyingPhone()
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.requests, ["whenInUse"])
        XCTAssertEqual(phone.notifications.requested, 0)
        phone.locations.authorization = .whenInUse
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.requests, ["whenInUse", "always"])
        XCTAssertEqual(phone.notifications.requested, 0)
        phone.locations.authorization = .always
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.notifications.requested, 1)
        await phone.watch.saved(server: phone.home)
        await phone.watch.activated()
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.requests, ["whenInUse", "always"])
        XCTAssertEqual(phone.notifications.requested, 1)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
    }

    func testNothingIsAskedWhileTheAppIsInTheBackgroundUntilItIsNextActive() async {
        let phone = qualifyingPhone()
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.requests, [])
        await phone.watch.activated()
        XCTAssertEqual(phone.locations.requests, ["whenInUse"])
    }

    func testNothingIsAskedWhileSavingIsOff() async {
        let phone = qualifyingPhone()
        OfflineSettings(defaults: phone.defaults).set(false)
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        await phone.watch.activated()
        XCTAssertEqual(phone.locations.requests, [])
    }

    func testNothingIsAskedWhenNoBookingQualifies() async {
        let phone = makeRig(.notDetermined)
        phone.save([ArrivalFixtures.segment(1, "flight", start: "2026-12-01T09:00", end: "2026-12-01T11:00", address: nil),
                    ArrivalFixtures.segment(2, "parking", start: "2026-11-01T09:00", end: "2026-11-05T18:00", address: "1 Main St"),
                    ArrivalFixtures.segment(3, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", address: "3 Inn Ave", status: "cancelled")])
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        await phone.watch.activated()
        XCTAssertEqual(phone.locations.requests, [])
        XCTAssertEqual(phone.notifications.requested, 0)
    }

    func testNothingIsAskedOnceLocationWasAnsweredInIOSSettings() async {
        let phone = makeRig(.denied)
        phone.save([ArrivalFixtures.parking()])
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.requests, [])
    }

    func testRefusingLocationStopsTheAsksAndTurningItOnLaterNeverAsksAgain() async {
        let phone = qualifyingPhone()
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        phone.locations.authorization = .denied
        await phone.watch.handle(.authorizationChanged)
        phone.locations.authorization = .whenInUse
        await phone.watch.handle(.authorizationChanged)
        phone.locations.authorization = .always
        await phone.watch.handle(.authorizationChanged)
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.requests, ["whenInUse"])
        XCTAssertEqual(phone.notifications.requested, 0)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
    }

    func testKeepingWhileUsingAsksNothingMoreAndWatchesNothing() async {
        let phone = qualifyingPhone()
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        phone.locations.authorization = .whenInUse
        await phone.watch.handle(.authorizationChanged)
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.requests, ["whenInUse", "always"])
        XCTAssertEqual(phone.notifications.requested, 0)
        XCTAssertEqual(phone.locations.monitoredIds, [])
    }

    func testTheAsksAreNotRepeatedByANewLaunch() async {
        let phone = qualifyingPhone()
        await phone.watch.foregrounded()
        await phone.watch.saved(server: phone.home)
        let again = ArrivalWatch(store: phone.store, places: phone.places, locations: phone.locations, notifications: phone.notifications,
                                 asks: ArrivalAsks(defaults: phone.defaults), settings: OfflineSettings(defaults: phone.defaults),
                                 server: { [home = phone.home] in home })
        phone.locations.authorization = .notDetermined
        await again.foregrounded()
        await again.saved(server: phone.home)
        XCTAssertEqual(phone.locations.requests, ["whenInUse"])
    }

    // MARK: Authorization changes (the design's "No switch" table)

    private func leaveSomeNotifications(_ phone: ArrivalRig) {
        phone.notifications.leaveDelivered("arrival-1")
        phone.notifications.leaveDelivered("arrival-3")
        phone.notifications.leaveDelivered("somewhere-else")
    }

    private func assertWithdrawn(_ phone: ArrivalRig) {
        XCTAssertEqual(phone.locations.monitoredIds, [])
        XCTAssertEqual(phone.notifications.current, ["somewhere-else"])
        XCTAssertNil(phone.store.loadArrival(server: phone.home))
        XCTAssertNil(phone.store.loadPlaces(server: phone.home))
        XCTAssertNotNil(phone.store.load(server: phone.home))
    }

    func testLocationNeverStopsEverythingAndDeletesTheFileAndTheCoordinates() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        phone.locations.authorization = .denied
        await phone.watch.handle(.authorizationChanged)
        assertWithdrawn(phone)
    }

    func testLocationAskNextTimeDoesTheSame() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        phone.locations.authorization = .notDetermined
        await phone.watch.handle(.authorizationChanged)
        assertWithdrawn(phone)
    }

    func testWhileUsingStopsTheRegionsAndNotificationsAndKeepsTheFilesForTheCard() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        phone.locations.authorization = .whenInUse
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds, [])
        XCTAssertEqual(phone.notifications.current, ["somewhere-else"])
        XCTAssertNotNil(phone.store.loadArrival(server: phone.home))
        XCTAssertNotNil(phone.store.loadPlaces(server: phone.home))
        XCTAssertNotNil(phone.store.load(server: phone.home))
    }

    func testPreciseLocationOffStopsEverythingAndDeletesNothing() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        phone.locations.hasPreciseLocation = false
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds, [])
        XCTAssertEqual(phone.notifications.current, ["somewhere-else"])
        XCTAssertNotNil(phone.store.loadArrival(server: phone.home))
        XCTAssertNotNil(phone.store.loadPlaces(server: phone.home))
        phone.locations.hasPreciseLocation = true
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1", "arrival-2", "arrival-3"])
    }

    func testTurningLocationBackOnResumesAtTheNextActivationWithNoNewAsk() async {
        let phone = await watching()
        phone.locations.authorization = .denied
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.locations.monitoredIds, [])
        phone.locations.authorization = .always
        await phone.watch.activated()
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1", "arrival-2", "arrival-3"])
        XCTAssertEqual(phone.locations.requests, [])
        XCTAssertEqual(phone.notifications.requested, 0)
    }

    // MARK: Every purge

    private func assertEverythingGone(_ phone: ArrivalRig, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(phone.locations.monitoredIds, [], file: file, line: line)
        XCTAssertEqual(phone.notifications.current, ["somewhere-else"], file: file, line: line)
        XCTAssertNil(phone.store.loadArrival(server: phone.home), file: file, line: line)
        XCTAssertNil(phone.store.loadPlaces(server: phone.home), file: file, line: line)
        XCTAssertFalse(FileManager.default.fileExists(atPath: phone.arrivalFile.path), file: file, line: line)
    }

    func testSigningOutStopsAndDeletesEverything() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        let sync = phone.makeSync()
        await sync.signedOut()
        await sync.arrivalSettled()
        assertEverythingGone(phone)
    }

    func testSwitchingSavingOffStopsAndDeletesEverything() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        let sync = phone.makeSync()
        await sync.setSaving(false)
        await sync.arrivalSettled()
        assertEverythingGone(phone)
    }

    func testAChangedServerStopsAndDeletesEverything() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        let sync = phone.makeSync()
        await sync.serverChanged(from: phone.home, to: URL(string: "https://other.example.com")!)
        await sync.arrivalSettled()
        assertEverythingGone(phone)
    }

    func testRemovingTheSavedTripsStopsAndDeletesEverything() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        let sync = phone.makeSync()
        await sync.remove()
        await sync.arrivalSettled()
        assertEverythingGone(phone)
    }

    func testA401StopsAndDeletesEverything() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        let sync = phone.makeSync(status: 401)
        await sync.sync()
        await sync.arrivalSettled()
        assertEverythingGone(phone)
    }

    func testNoServerStopsAndDeletesEverything() async {
        let phone = await watching()
        leaveSomeNotifications(phone)
        let sync = phone.makeSync(hasServer: false)
        await sync.sync()
        await sync.arrivalSettled()
        assertEverythingGone(phone)
    }

    func testASaveHandsTheWatchTheServerAndAPurgeClearsIt() async {
        let phone = makeRig()
        let watcher = ArrivalRecordingWatch()
        let fetching = ArrivalFakeSaves()
        fetching.data = ArrivalFixtures.tripsJSON([ArrivalFixtures.parking()])
        let sync = OfflineSync(store: phone.store, settings: OfflineSettings(defaults: phone.defaults), fetching: fetching,
                               arrival: phone.places, server: { [home = phone.home] in home }, bearer: { "wpa_token" }, watching: watcher)
        let outcome = await sync.sync()
        await sync.arrivalSettled()
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(watcher.saves, [phone.home])
        XCTAssertEqual(watcher.clears, 0)
        await sync.signedOut()
        await sync.arrivalSettled()
        XCTAssertEqual(watcher.clears, 1)
    }

    // MARK: Interleavings, one-shot bookings, what the file keeps

    func testAPurgeDuringTheNotificationSettingsCheckPostsNothing() async {
        let phone = await watching()
        phone.notifications.beforeAllowsAlerts = { await phone.watch.cleared() }
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.posted.count, 0)
        XCTAssertEqual(phone.notifications.current, [])
    }

    func testAPurgeThatAlsoDeletesTheFilesDuringTheCheckPostsNothing() async {
        let phone = await watching()
        phone.notifications.beforeAllowsAlerts = {
            await phone.watch.cleared()
            try? phone.store.purgeAll()
        }
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.posted.count, 0)
        XCTAssertEqual(phone.notifications.current, [])
    }

    func testLocationRevokedDuringTheNotificationSettingsCheckPostsNothing() async {
        let phone = await watching()
        phone.notifications.beforeAllowsAlerts = { phone.locations.authorization = .whenInUse }
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertEqual(phone.notifications.posted.count, 0)
    }

    func testAFinishedOneShotBookingReleasesItsRegionButKeepsItsHistoryAndNotification() async throws {
        let phone = makeRig()
        var segments: [[String: Any]] = []
        for id in 1...16 {
            let day = String(format: "2026-12-%02d", id)
            segments.append(ArrivalFixtures.segment(id, "hotel", start: "\(day)T15:00", end: "2026-12-30T11:00", address: "\(id) Inn Ave"))
            phone.geocoder.answers["\(id) Inn Ave"] = PlacePoint(latitude: 39.0 + Double(id) / 100, longitude: -105.0)
        }
        phone.save(segments)
        await phone.watch.saved(server: phone.home)
        XCTAssertEqual(phone.locations.monitoredIds.count, 15)
        XCTAssertFalse(phone.locations.monitoredIds.contains("arrival-16"))
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 13))
        XCTAssertEqual(phone.notifications.current, ["arrival-1"])
        XCTAssertEqual(phone.locations.monitoredIds.count, 15)
        XCTAssertFalse(phone.locations.monitoredIds.contains("arrival-1"))
        XCTAssertTrue(phone.locations.monitoredIds.contains("arrival-16"))
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let file = try decoder.decode(ArrivalFileContent.self, from: Data(try XCTUnwrap(phone.arrivalText).utf8))
        XCTAssertNotNil(file.watched.first { $0.place.segmentId == 1 }?.notifiedAt)
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 14))
        XCTAssertEqual(phone.notifications.posted.count, 1)
        phone.clock.date = ArrivalFixtures.moment(2026, 12, 2, 1)
        await phone.watch.activated()
        XCTAssertFalse(phone.notifications.current.contains("arrival-1"))
    }

    func testAParkingBookingKeepsItsRegionAfterNotifying() async {
        let phone = await watching()
        await enter(phone, 1, at: ArrivalFixtures.moment(2026, 12, 1, 8))
        XCTAssertTrue(phone.locations.monitoredIds.contains("arrival-1"))
    }

    private func assertTheFileHoldsOnlyTheWindowAndTheAlertTime(_ phone: ArrivalRig, alertAt: Date, file: StaticString = #filePath, line: UInt = #line) throws {
        let text = try XCTUnwrap(phone.arrivalText, file: file, line: line)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)), file: file, line: line)
        var found: [(String, String)] = []
        func collect(_ value: Any, key: String?) {
            if let dictionary = value as? [String: Any] {
                for (name, inner) in dictionary { collect(inner, key: name) }
            } else if let list = value as? [Any] {
                for inner in list { collect(inner, key: key) }
            } else if let string = value as? String, let key {
                found.append((key, string))
            }
        }
        collect(object, key: nil)
        XCTAssertEqual(Set(found.map { $0.0 }), ["kind", "opens", "closes", "notifiedAt"], file: file, line: line)
        let alerts = found.filter { $0.0 == "notifiedAt" }.map { $0.1 }
        XCTAssertEqual(alerts, [ISO8601DateFormatter().string(from: alertAt)], file: file, line: line)
    }

    func testAfterAParkingEntryTheArrivalFileHoldsNoInstantButTheWindowAndWhenTheAlertLastFired() async throws {
        let phone = await watching()
        let at = ArrivalFixtures.moment(2026, 12, 1, 8)
        await enter(phone, 1, at: at)
        try assertTheFileHoldsOnlyTheWindowAndTheAlertTime(phone, alertAt: at)
    }

    func testAfterARentalPickupEntryTheArrivalFileHoldsNoInstantButTheWindowAndWhenTheAlertLastFired() async throws {
        let phone = await watching()
        let at = ArrivalFixtures.moment(2026, 12, 1, 9)
        await enter(phone, 2, at: at)
        try assertTheFileHoldsOnlyTheWindowAndTheAlertTime(phone, alertAt: at)
    }

    func testAfterAHotelEntryTheArrivalFileHoldsNoInstantButTheWindowAndWhenTheAlertLastFired() async throws {
        let phone = await watching()
        let at = ArrivalFixtures.moment(2026, 12, 1, 13)
        await enter(phone, 3, at: at)
        try assertTheFileHoldsOnlyTheWindowAndTheAlertTime(phone, alertAt: at)
    }

    func testAReportThatChangesNothingAsksTheGeocoderNothing() async {
        let phone = makeRig()
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.hotel()])
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot]
        await phone.watch.saved(server: phone.home)
        let asked = phone.geocoder.asked.count
        XCTAssertEqual(asked, 2)
        await phone.watch.handle(.authorizationChanged)
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.geocoder.asked.count, asked)
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1"])
    }

    func testAReportThatChangesTheStandingLooksTheMissedAddressUpAgain() async {
        let phone = makeRig()
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.hotel()])
        phone.geocoder.answers = ["1 Main St": ArrivalFixtures.lot]
        await phone.watch.saved(server: phone.home)
        phone.locations.hasPreciseLocation = false
        await phone.watch.handle(.authorizationChanged)
        XCTAssertEqual(phone.geocoder.asked.count, 3)
    }

    func testAPurgeDuringALookupStopsTheRefreshAndLeavesNothingWatched() async throws {
        let phone = makeRig()
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking(), ArrivalFixtures.hotel()])
        let gate = ArrivalGate()
        phone.geocoder.duringAsk = { await gate.wait() }
        let refresh = Task { await phone.watch.saved(server: phone.home) }
        for _ in 0..<200 where phone.geocoder.asked.isEmpty {
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        await phone.watch.cleared()
        gate.open()
        await refresh.value
        XCTAssertEqual(phone.geocoder.asked.count, 1)
        XCTAssertEqual(phone.locations.monitoredIds, [])
    }

    func testASaveForANewServerDuringARefreshForTheOldOneEndsWithTheNewServersRegions() async throws {
        let phone = makeRig()
        answers(phone.geocoder)
        let other = URL(string: "https://other.example.com")!
        phone.save([ArrivalFixtures.parking()])
        try phone.store.save(ArrivalFixtures.tripsJSON([ArrivalFixtures.hotel()]), version: 1, for: other)
        let gate = ArrivalGate()
        phone.geocoder.duringAsk = { await gate.wait() }
        let old = Task { await phone.watch.saved(server: phone.home) }
        for _ in 0..<200 where phone.geocoder.asked.isEmpty {
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        let new = Task { await phone.watch.saved(server: other) }
        try await Task.sleep(nanoseconds: 100_000_000)
        gate.open()
        await old.value
        await new.value
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-3"])
    }

    func testRegionStartsAndStopsAreSeenByTheNextReadBeforeTheSystemHasRunThem() {
        let live = LiveArrivalLocations()
        live.monitor(id: "arrival-9", latitude: 39.7, longitude: -104.9, radius: 250)
        XCTAssertTrue(live.monitoredIds.contains("arrival-9"))
        live.stopMonitoring(id: "arrival-9")
        XCTAssertFalse(live.monitoredIds.contains("arrival-9"))
    }

    func testTwoRefreshesAtOnceLookEachAddressUpOnce() async {
        let phone = makeRig()
        answers(phone.geocoder)
        phone.save([ArrivalFixtures.parking()])
        async let first: Void = phone.watch.saved(server: phone.home)
        async let second: Void = phone.watch.activated()
        _ = await (first, second)
        XCTAssertEqual(phone.geocoder.asked.filter { $0 == "1 Main St" }.count, 1)
    }

    func testASecondSaveWhileTheFirstLookupIsSuspendedEndsWithTheLatestSavesRegions() async throws {
        let phone = makeRig()
        answers(phone.geocoder)
        let gate = ArrivalGate()
        phone.geocoder.duringAsk = { await gate.wait() }
        let saves = ArrivalFakeSaves()
        let sync = phone.makeSync(data: ArrivalFixtures.tripsJSON([ArrivalFixtures.parking()]), using: saves)
        let first = await sync.sync()
        XCTAssertEqual(first, .saved)
        for _ in 0..<200 where phone.geocoder.asked.isEmpty {
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertFalse(phone.geocoder.asked.isEmpty)
        saves.data = ArrivalFixtures.tripsJSON([ArrivalFixtures.parking(), ArrivalFixtures.hotel()])
        let second = await sync.sync()
        XCTAssertEqual(second, .saved)
        gate.open()
        await sync.arrivalSettled()
        XCTAssertEqual(phone.locations.monitoredIds, ["arrival-1", "arrival-3"])
    }
}
