import XCTest
@testable import Waypoint

private final class FakeGeocoder: AddressGeocoding, @unchecked Sendable {
    var answers: [String: PlacePoint] = [:]
    private(set) var asked: [String] = []

    func point(for address: String) async -> PlacePoint? {
        asked.append(address)
        return answers[address]
    }
}

private final class FakePermission: LocationPermission, @unchecked Sendable {
    var isAllowed: Bool

    init(_ allowed: Bool) {
        isAllowed = allowed
    }
}

private final class ArrivalFakeFetching: OfflineFetching, @unchecked Sendable {
    var data = Data()

    func fetch(server: URL, bearer: String?) async throws -> (data: Data, status: Int) {
        (data, 200)
    }
}

final class ArrivalPlacesTests: XCTestCase {
    private var root: URL!
    private var suite: String!
    private var defaults: UserDefaults!
    private var store: OfflineStore!
    private var geocoder: FakeGeocoder!
    private var permission: FakePermission!
    private let home = URL(string: "https://waypoint.example.com")!
    private let lot = PlacePoint(latitude: 39.7392, longitude: -104.9903)
    private let inn = PlacePoint(latitude: 39.75, longitude: -105.0)
    private let counter = PlacePoint(latitude: 39.8, longitude: -104.8)
    private let airport = PlacePoint(latitude: 39.8561, longitude: -104.6737)

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    private static func moment(_ year: Int, _ month: Int, _ day: Int, _ hour: Int, _ minute: Int = 0, zone: String = "America/Denver") -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: zone)!
        return calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute))!
    }

    private let storeNow = ArrivalPlacesTests.moment(2026, 11, 10, 12)

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("arrival-places-\(UUID().uuidString)", isDirectory: true)
        suite = "arrival-places-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        let saved = storeNow
        store = OfflineStore(root: root, calendar: Self.utc, now: { saved })
        geocoder = FakeGeocoder()
        permission = FakePermission(true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    // MARK: Fixtures

    private func finder(now: Date? = nil) -> ArrivalPlaces {
        let fixed = now ?? storeNow
        return ArrivalPlaces(store: store, geocoder: geocoder, permission: permission, calendar: Self.utc, now: { fixed })
    }

    private func segment(_ id: Int, _ kind: String, start: String, end: String, zone: String = "America/Denver", status: String = "confirmed",
                         origin: String? = nil, address: String? = nil, flag: String? = nil) -> [String: Any] {
        var details: [String: Any] = ["seat": "12A", "phone": "555-0100"]
        if let address { details["address"] = address }
        if let flag { details["time_unknown"] = flag }
        var entry: [String: Any] = ["id": id, "kind": kind, "status": status, "start_local": start, "start_zone": zone,
                                    "end_local": end, "end_zone": zone, "confirmation": "ABC123", "details": details]
        if let origin { entry["origin"] = origin }
        return entry
    }

    private func tripsJSON(_ segments: [[String: Any]], airports: [[String: Any]]? = nil) -> Data {
        var entry: [String: Any] = ["trip": ["id": 7, "name": "Denver", "start_date": "2026-12-01", "end_date": "2026-12-08",
                                             "segments": segments] as [String: Any],
                                    "messages": [] as [Any], "codes": [] as [Any]]
        if let airports { entry["airports"] = airports }
        return try! JSONSerialization.data(withJSONObject: ["version": 1, "trips": [entry]])
    }

    private func save(_ segments: [[String: Any]], airports: [[String: Any]]? = nil) {
        try! store.save(tripsJSON(segments, airports: airports), version: 1, for: home)
    }

    private var denver: [String: Any] {
        ["code": "DEN", "latitude": airport.latitude, "longitude": airport.longitude]
    }

    private func parking(_ id: Int = 1, address: String? = "1 Main St") -> [String: Any] {
        segment(id, "parking", start: "2026-12-01T09:00", end: "2026-12-05T18:00", address: address)
    }

    // MARK: Which bookings qualify

    func testOnlyParkingCarPickupsAndHotelsQualify() async {
        var segments = [parking(1), segment(2, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", address: "2 Rental Rd"),
                        segment(3, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", address: "3 Inn Ave")]
        for (offset, kind) in ["flight", "train", "cruise", "visit"].enumerated() {
            segments.append(segment(10 + offset, kind, start: "2026-12-01T09:00", end: "2026-12-01T11:00", address: "4 Else St"))
        }
        save(segments)
        geocoder.answers = ["1 Main St": lot, "2 Rental Rd": counter, "3 Inn Ave": inn, "4 Else St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.map(\.segmentId).sorted(), [1, 2, 3])
        XCTAssertEqual(Set(found.map(\.kind)), [.parking, .rentalPickup, .hotel])
        XCTAssertFalse(geocoder.asked.contains("4 Else St"))
    }

    func testACancelledBookingIsLeftOut() async {
        save([segment(1, "parking", start: "2026-12-01T09:00", end: "2026-12-05T18:00", status: "cancelled", address: "1 Main St"),
              parking(2, address: "1 Main St")])
        geocoder.answers = ["1 Main St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.map(\.segmentId), [2])
    }

    func testQualifiesNeedsNoPermissionAndNoPoint() async {
        permission.isAllowed = false
        save([segment(1, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00")])
        let yes = await finder().qualifies(server: home)
        XCTAssertTrue(yes)
        XCTAssertTrue(geocoder.asked.isEmpty)
        save([segment(2, "flight", start: "2026-12-01T09:00", end: "2026-12-01T11:00")])
        let no = await finder().qualifies(server: home)
        XCTAssertFalse(no)
    }

    // MARK: Windows

    func testParkingOpensTwoHoursBeforeEntryAndEndsAtTheExit() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.opens, Self.moment(2026, 12, 1, 7))
        XCTAssertEqual(found.first?.closes, Self.moment(2026, 12, 5, 18))
        XCTAssertEqual(found.first?.radius, 250)
    }

    func testParkingAfterItsExitIsLeftOutAndBeforeItsEntryIsKept() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        let after = await finder(now: Self.moment(2026, 12, 5, 18, 1)).refresh(server: home)
        XCTAssertTrue(after.isEmpty)
        let before = await finder(now: Self.moment(2026, 11, 20, 9)).refresh(server: home)
        XCTAssertEqual(before.map(\.segmentId), [1])
    }

    func testAParkingBookingWithNoTimesHasEveryDayToTheEndOfTheLast() async {
        save([segment(1, "parking", start: "2026-12-01T00:00", end: "2026-12-05T00:00", address: "1 Main St")])
        geocoder.answers = ["1 Main St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.opens, Self.moment(2026, 12, 1, 0))
        XCTAssertEqual(found.first?.closes, Self.moment(2026, 12, 6, 0))
    }

    func testARentalPickupRunsFromTwoHoursBeforeToFourHoursAfter() async {
        save([segment(1, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", address: "2 Rental Rd")])
        geocoder.answers = ["2 Rental Rd": counter]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.opens, Self.moment(2026, 12, 1, 8))
        XCTAssertEqual(found.first?.closes, Self.moment(2026, 12, 1, 14))
        XCTAssertEqual(found.first?.radius, 300)
        let late = await finder(now: Self.moment(2026, 12, 1, 14, 1)).refresh(server: home)
        XCTAssertTrue(late.isEmpty)
    }

    func testAHotelRunsFromThreeHoursBeforeCheckInToMidnightThere() async {
        save([segment(1, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", address: "3 Inn Ave")])
        geocoder.answers = ["3 Inn Ave": inn]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.opens, Self.moment(2026, 12, 1, 12))
        XCTAssertEqual(found.first?.closes, Self.moment(2026, 12, 2, 0))
        XCTAssertEqual(found.first?.radius, 200)
        let next = await finder(now: Self.moment(2026, 12, 2, 0, 1)).refresh(server: home)
        XCTAssertTrue(next.isEmpty)
    }

    func testAnEarlyCheckInDoesNotOpenBeforeTheCheckInDay() async {
        save([segment(1, "hotel", start: "2026-12-01T01:00", end: "2026-12-05T11:00", address: "3 Inn Ave")])
        geocoder.answers = ["3 Inn Ave": inn]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.opens, Self.moment(2026, 12, 1, 0))
    }

    func testTheZoneIsTheBookingsOwn() async {
        save([segment(1, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", zone: "Pacific/Auckland", address: "3 Inn Ave")])
        geocoder.answers = ["3 Inn Ave": inn]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.opens, Self.moment(2026, 12, 1, 12, zone: "Pacific/Auckland"))
    }

    func testPlacesAreOrderedBySoonestWindow() async {
        save([segment(1, "hotel", start: "2026-12-03T15:00", end: "2026-12-05T11:00", address: "3 Inn Ave"), parking(2)])
        geocoder.answers = ["3 Inn Ave": inn, "1 Main St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.map(\.segmentId), [2, 1])
    }

    // MARK: The point

    func testTheAddressIsUsedBeforeTheAirport() async {
        save([segment(1, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", origin: "DEN", address: "2 Rental Rd")], airports: [denver])
        geocoder.answers = ["2 Rental Rd": counter]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.latitude, counter.latitude)
        XCTAssertEqual(found.first?.longitude, counter.longitude)
        XCTAssertEqual(found.first?.radius, 300)
    }

    func testACarWithOnlyAnAirportUsesTheAirportWithoutALookup() async {
        save([segment(1, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", origin: "den")], airports: [denver])
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.first?.latitude, airport.latitude)
        XCTAssertEqual(found.first?.longitude, airport.longitude)
        XCTAssertEqual(found.first?.radius, 2_000)
        XCTAssertTrue(geocoder.asked.isEmpty)
    }

    func testAnAddressThatCannotBeFoundFallsBackToTheAirport() async {
        save([segment(1, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", origin: "DEN", address: "Nowhere Lane")], airports: [denver])
        let found = await finder().refresh(server: home)
        XCTAssertEqual(geocoder.asked, ["Nowhere Lane"])
        XCTAssertEqual(found.first?.radius, 2_000)
    }

    func testABookingWithNeitherIsLeftOut() async {
        save([segment(1, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00"),
              segment(2, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", origin: "XYZ"),
              segment(3, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", address: "Nowhere Lane"),
              parking(4, address: "   ")], airports: [denver])
        let found = await finder().refresh(server: home)
        XCTAssertTrue(found.isEmpty)
    }

    func testACopySavedBeforeAirportsLeavesAnAirportOnlyPickupOut() async {
        save([segment(1, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", origin: "DEN")])
        let found = await finder().refresh(server: home)
        XCTAssertTrue(found.isEmpty)
    }

    func testAHotelsOriginIsNeverAPickupAirport() async {
        save([segment(1, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", origin: "DEN")], airports: [denver])
        let found = await finder().refresh(server: home)
        XCTAssertTrue(found.isEmpty)
    }

    // MARK: Permission

    func testNothingIsLookedUpWithoutLocationPermission() async {
        permission.isAllowed = false
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertTrue(found.isEmpty)
        XCTAssertTrue(geocoder.asked.isEmpty)
        XCTAssertNil(store.loadPlaces(server: home))
    }

    func testWithdrawingPermissionDeletesWhatWasFound() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        await places.refresh(server: home)
        XCTAssertNotNil(store.loadPlaces(server: home))
        permission.isAllowed = false
        await places.refresh(server: home)
        XCTAssertNil(store.loadPlaces(server: home))
        let remaining = await places.places(server: home)
        XCTAssertTrue(remaining.isEmpty)
    }

    func testNothingIsSavedWhenTheTripsAreNot() async {
        let found = await finder().refresh(server: home)
        XCTAssertTrue(found.isEmpty)
        XCTAssertTrue(geocoder.asked.isEmpty)
        XCTAssertNil(store.loadPlaces(server: home))
    }

    // MARK: The cache

    func testTheSameAddressIsLookedUpOnceAcrossRefreshes() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        await places.refresh(server: home)
        await places.refresh(server: home)
        XCTAssertEqual(geocoder.asked, ["1 Main St"])
        let kept = await places.places(server: home)
        XCTAssertEqual(kept.count, 1)
    }

    func testTheSameAddressOnTwoBookingsIsLookedUpOnce() async {
        save([parking(1, address: "1 Main St"), segment(2, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", address: " 1 Main St ")])
        geocoder.answers = ["1 Main St": lot]
        let found = await finder().refresh(server: home)
        XCTAssertEqual(found.count, 2)
        XCTAssertEqual(geocoder.asked, ["1 Main St"])
    }

    func testTheCacheSurvivesANewSaveOfTheTrips() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        await places.refresh(server: home)
        save([parking()])
        XCTAssertNotNil(store.loadPlaces(server: home))
        await places.refresh(server: home)
        XCTAssertEqual(geocoder.asked, ["1 Main St"])
    }

    func testAFailedLookupIsTriedAgainNextTime() async {
        save([parking()])
        let places = finder()
        await places.refresh(server: home)
        geocoder.answers = ["1 Main St": lot]
        let found = await places.refresh(server: home)
        XCTAssertEqual(geocoder.asked, ["1 Main St", "1 Main St"])
        XCTAssertEqual(found.count, 1)
    }

    func testTheFileKeepsOnlyTheAddressesOfTheCurrentTripsAndOnlyTheirHashes() async throws {
        save([parking(1, address: "1 Main St"), segment(2, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", address: "3 Inn Ave")])
        geocoder.answers = ["1 Main St": lot, "3 Inn Ave": inn]
        let places = finder()
        await places.refresh(server: home)
        save([parking(1, address: "1 Main St")])
        await places.refresh(server: home)
        let data = try XCTUnwrap(store.loadPlaces(server: home))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let cached = try XCTUnwrap(object["geocoded"] as? [String: Any])
        XCTAssertEqual(Set(cached.keys), [ArrivalPlaces.key("1 Main St")])
        let text = String(decoding: data, as: UTF8.self)
        XCTAssertFalse(text.contains("Main St"))
        XCTAssertFalse(text.contains("ABC123"))
    }

    func testTheAddressKeyIsTheSHA256OfTheText() {
        XCTAssertEqual(ArrivalPlaces.key("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }

    // MARK: Purge and protection

    func testPurgeOfOneServerDeletesTheFile() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        await finder().refresh(server: home)
        XCTAssertNotNil(store.loadPlaces(server: home))
        try? store.purge(server: home)
        XCTAssertNil(store.loadPlaces(server: home))
    }

    func testPurgeAllDeletesTheFile() async {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        await finder().refresh(server: home)
        try? store.purgeAll()
        XCTAssertNil(store.loadPlaces(server: home))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }

    func testTheFileCarriesCompleteFileProtection() async throws {
        save([parking()])
        geocoder.answers = ["1 Main St": lot]
        await finder().refresh(server: home)
        let folder = root.appendingPathComponent(OfflineStore.folderName(for: home), isDirectory: true)
        let file = folder.appendingPathComponent("arrival-places.json")
        let value = try FileManager.default.attributesOfItem(atPath: file.path)[.protectionKey] as? FileProtectionType
        XCTAssertEqual(value, FileProtectionType.complete)
    }

    func testAPlacesFileIsNeverWrittenWithoutASavedCopy() throws {
        try store.savePlaces(Data("{}".utf8), for: home)
        XCTAssertNil(store.loadPlaces(server: home))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }

    // MARK: After a save

    private func makeSync(_ places: ArrivalPlaces, data: Data) -> OfflineSync {
        let fetching = ArrivalFakeFetching()
        fetching.data = data
        return OfflineSync(store: store, settings: OfflineSettings(defaults: defaults), fetching: fetching, arrival: places,
                           server: { [home] in home }, bearer: { "wpa_token" })
    }

    func testASuccessfulSaveFindsThePlaces() async {
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        let sync = makeSync(places, data: tripsJSON([parking()]))
        let outcome = await sync.sync()
        await sync.arrivalSettled()
        XCTAssertEqual(outcome, .saved)
        let found = await places.places(server: home)
        XCTAssertEqual(found.map(\.segmentId), [1])
    }

    func testASaveWithoutLocationPermissionLooksNothingUp() async {
        permission.isAllowed = false
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        let sync = makeSync(places, data: tripsJSON([parking()]))
        await sync.sync()
        await sync.arrivalSettled()
        XCTAssertTrue(geocoder.asked.isEmpty)
        XCTAssertNil(store.loadPlaces(server: home))
    }

    func testSigningOutDeletesThePlacesWithTheTrips() async {
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        let sync = makeSync(places, data: tripsJSON([parking()]))
        await sync.sync()
        await sync.arrivalSettled()
        XCTAssertNotNil(store.loadPlaces(server: home))
        await sync.signedOut()
        XCTAssertNil(store.loadPlaces(server: home))
        XCTAssertNil(store.load(server: home))
    }

    func testSwitchingSavingOffDeletesThePlaces() async {
        geocoder.answers = ["1 Main St": lot]
        let places = finder()
        let sync = makeSync(places, data: tripsJSON([parking()]))
        await sync.sync()
        await sync.arrivalSettled()
        await sync.setSaving(false)
        XCTAssertNil(store.loadPlaces(server: home))
    }
}
