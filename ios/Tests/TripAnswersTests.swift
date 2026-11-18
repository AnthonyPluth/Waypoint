import XCTest
@testable import Waypoint

/// Made-up trips for the Siri and Shortcuts answers. They are written the way the server's `GET /api/offline` reply is (trip,
/// its segments, the messages and the cities beside the trip) and carry canary values wherever a private value could be.
enum AnswerFixtures {
    static let canaries = ["CANARYCONF", "CANARYSEAT", "CANARYROOM", "CANARYPHONE", "CANARYTERM", "CANARYGATE", "CANARYTRAVELLER",
                           "CANARYMANAGE", "CANARYSUBJECT", "CANARYEMAIL", "CANARYCODE", "CANARYSPACE"]

    static let denver = "America/Denver"
    static let newYork = "America/New_York"
    static let auckland = "Pacific/Auckland"

    static let phone: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    /// The moment a wall-clock time is in a zone.
    static func date(_ wall: String, _ zone: String = denver) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: zone)!
        let parts = WallClock(wall)!
        return calendar.date(from: DateComponents(year: parts.year, month: parts.month, day: parts.day, hour: parts.hour, minute: parts.minute))!
    }

    static func orNull(_ text: String?) -> Any {
        (text as Any?) ?? NSNull()
    }

    static func flight(_ id: Int, _ start: String, _ end: String, from: String = "DEN", to: String = "GJT", number: String? = "EA 214",
                       startZone: String = denver, endZone: String = denver, status: String = "confirmed", untimed: Bool = false) -> [String: Any] {
        var details: [String: Any] = ["terminal": "CANARYTERM", "seat": "CANARYSEAT", "gate": "CANARYGATE", "phone": "CANARYPHONE"]
        if let number { details["flight_number"] = number }
        if untimed { details["time_unknown"] = "yes" }
        return segment(id, "flight", start, end, startZone: startZone, endZone: endZone, origin: from, destination: to, status: status, details: details)
    }

    static func hotel(_ id: Int, _ name: String, _ start: String, _ end: String, city: String? = "Grand Junction",
                      address: String? = "100 Example Avenue, Grand Junction", zone: String = denver, status: String = "confirmed",
                      untimed: Bool = false) -> [String: Any] {
        var details: [String: Any] = ["room": "CANARYROOM", "phone": "CANARYPHONE"]
        if let address { details["address"] = address }
        if untimed { details["time_unknown"] = "yes" }
        return segment(id, "hotel", start, end, startZone: zone, endZone: zone, origin: name, destination: city, status: status, details: details)
    }

    static func parking(_ id: Int, _ lot: String?, _ start: String, _ end: String, zone: String = denver, status: String = "confirmed",
                        provider: String? = "Provider Example") -> [String: Any] {
        let details: [String: Any] = ["address": "1 Lot Road, Grand Junction", "space": "CANARYSPACE", "code": "CANARYCODE", "phone": "CANARYPHONE"]
        return segment(id, "parking", start, end, startZone: zone, endZone: zone, origin: lot, destination: nil, status: status,
                       details: details, provider: provider)
    }

    static func segment(_ id: Int, _ kind: String, _ start: String, _ end: String, startZone: String, endZone: String, origin: String?,
                        destination: String?, status: String, details: [String: Any], provider: String? = "Provider Example") -> [String: Any] {
        ["id": id, "trip_id": 1, "kind": kind, "status": status, "confirmation": "CANARYCONF", "provider": orNull(provider),
         "start_local": start, "start_zone": startZone, "end_local": end, "end_zone": endZone,
         "origin": orNull(origin), "destination": orNull(destination), "details": details,
         "manage_url": "https://example.com/CANARYMANAGE",
         "travelers": [["person_id": 9, "name": "CANARYTRAVELLER"] as [String: Any]]]
    }

    static func trip(_ id: Int, _ name: String, _ segments: [[String: Any]], destination: String? = nil,
                     cities: [String: String] = ["DEN": "Denver", "GJT": "Grand Junction", "JFK": "New York"]) -> [String: Any] {
        ["trip": ["id": id, "name": name, "start_date": "2026-11-16", "end_date": "2026-12-30", "destination": orNull(destination),
                  "segments": segments] as [String: Any],
         "messages": [["id": 1, "subject": "CANARYSUBJECT", "text": "CANARYEMAIL"] as [String: Any]],
         "cities": cities]
    }

    static func reply(_ trips: [[String: Any]], version: Int = 1) -> Data {
        try! JSONSerialization.data(withJSONObject: ["version": version, "trips": trips])
    }

    static func everything(in answer: Answer) -> [String] {
        [answer.spoken] + (answer.card?.texts ?? [])
    }
}

private final class FailingProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var seen = 0

    static var requests: Int {
        lock.lock()
        defer { lock.unlock() }
        return seen
    }

    static func reset() {
        lock.lock()
        seen = 0
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        lock.lock()
        seen += 1
        lock.unlock()
        return true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
    }

    override func stopLoading() {}
}

final class TripAnswersTests: XCTestCase {
    private var root: URL!
    private let home = URL(string: "https://waypoint.example.com")!
    private let savedTwoHoursAgo = AnswerFixtures.date("2026-11-18T03:00")

    override func setUp() {
        super.setUp()
        root = FileManager.default.temporaryDirectory.appendingPathComponent("trip-answers-\(UUID().uuidString)", isDirectory: true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: root)
        super.tearDown()
    }

    /// Saves the reply in a real `OfflineStore` and reads it back through `SavedTripsReader`, as an intent does.
    private func saved(_ trips: [[String: Any]], savedAt: Date? = nil) throws -> SavedCopy {
        let savedAt = savedAt ?? savedTwoHoursAgo
        let store = TripFixtures.store(at: root, now: savedAt)
        try store.save(AnswerFixtures.reply(trips), version: 1, for: home)
        guard case .copy(let copy) = SavedTripsReader.read(store, server: home) else {
            XCTFail("the saved copy was not read")
            throw OfflineStoreError.notATripSet
        }
        return copy
    }

    private func answers(at now: Date) -> TripAnswers {
        TripAnswers(now: now, calendar: AnswerFixtures.phone)
    }

    private let wednesday5am = AnswerFixtures.date("2026-11-18T05:00")

    // MARK: The read model

    func testTheReadModelHoldsOnlyWhatAnAnswerUses() {
        func labels(_ value: Any) -> Set<String> { Set(Mirror(reflecting: value).children.compactMap { $0.label }) }
        let booking = SavedBooking(id: 1, kind: "flight", startLocal: "2026-11-20T07:40", startZone: "America/Denver", endLocal: "2026-11-20T08:45", endZone: "America/Denver")
        XCTAssertEqual(labels(booking), ["id", "kind", "status", "startLocal", "startZone", "endLocal", "endZone", "origin", "destination",
                                         "provider", "flightNumber", "address", "timeUnknown"])
        XCTAssertEqual(labels(SavedTrip(id: 1, name: "Trip")), ["id", "name", "startDate", "endDate", "destination", "cities", "bookings"])
    }

    func testTheReaderDecodesTheTripsBookingsAndCities() throws {
        let copy = try saved([AnswerFixtures.trip(4, "Grand Junction", [AnswerFixtures.flight(12, "2026-11-20T07:40", "2026-11-20T08:45")], destination: "Grand Junction")])
        let trip = try XCTUnwrap(copy.trips.first)
        XCTAssertEqual([trip.id, trip.name, trip.destination ?? "", trip.startDate ?? "", trip.endDate ?? ""] as [AnyHashable],
                       [4, "Grand Junction", "Grand Junction", "2026-11-16", "2026-12-30"])
        XCTAssertEqual(trip.cities["DEN"], "Denver")
        let booking = try XCTUnwrap(trip.bookings.first)
        XCTAssertEqual(booking, SavedBooking(id: 12, kind: "flight", status: "confirmed", startLocal: "2026-11-20T07:40", startZone: "America/Denver",
                                             endLocal: "2026-11-20T08:45", endZone: "America/Denver", origin: "DEN", destination: "GJT",
                                             provider: "Provider Example", flightNumber: "EA 214", address: nil, timeUnknown: false))
    }

    func testOnlyTheExactValueYesMarksTheTimesUnknown() throws {
        func read(_ flag: String?) throws -> Bool {
            var segment = AnswerFixtures.flight(12, "2026-11-20T07:40", "2026-11-20T08:45")
            var details = segment["details"] as! [String: Any]
            details["time_unknown"] = flag
            segment["details"] = details
            let copy = try saved([AnswerFixtures.trip(1, "Trip", [segment])])
            return try XCTUnwrap(copy.trips.first?.bookings.first).timeUnknown
        }
        XCTAssertTrue(try read("yes"))
        XCTAssertFalse(try read("no"))
        XCTAssertFalse(try read(nil))
        XCTAssertFalse(try read(""))
        XCTAssertFalse(try read("maybe"))
        XCTAssertFalse(try read("YES"))
    }

    func testABookingThatIsNotAFlightAtMidnightHasNoTimeEvenWithoutTheFlag() throws {
        let midnight = AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T00:00", "2026-11-20T00:00")
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [midnight])])
        let booking = try XCTUnwrap(copy.trips.first?.bookings.first)
        XCTAssertFalse(booking.timeUnknown)
        XCTAssertTrue(booking.datedOnly)
        let subject = answers(at: AnswerFixtures.date("2026-11-18T20:00"))
        XCTAssertEqual(subject.tonight(copy).spoken, "Tonight you're staying at Hotel Example in Grand Junction. You check out Friday.")
        XCTAssertNil(subject.tonight(copy).card?.checkOut?.time)
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-20T15:00")).checkOut(copy).spoken, "You check out of Hotel Example today.")
    }

    func testOnlyOneEndAtMidnightKeepsAStayTimedAndAFlightAtMidnightStaysTimed() throws {
        let oneEnd = AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T00:00", "2026-11-20T11:00")
        let flight = AnswerFixtures.flight(13, "2026-11-20T00:00", "2026-11-20T01:30")
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [oneEnd, flight])])
        let bookings = try XCTUnwrap(copy.trips.first?.bookings)
        XCTAssertEqual(bookings.map(\.datedOnly), [false, false])
        let both = AnswerFixtures.flight(14, "2026-11-21T00:00", "2026-11-21T00:00")
        let flightsCopy = try saved([AnswerFixtures.trip(1, "Trip", [both])])
        XCTAssertEqual(flightsCopy.trips.first?.bookings.first?.datedOnly, false)
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(flightsCopy).page, "#trip/1/flight/14")
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-18T20:00")).tonight(copy).spoken,
                       "Tonight you're staying at Hotel Example in Grand Junction. You check out Friday at 11 am.")
    }

    func testAFlightMarkedNoForUnknownTimeIsStillTheNextFlightAndAHotelKeepsItsCheckOutTime() throws {
        var flight = AnswerFixtures.flight(13, "2026-11-20T07:40", "2026-11-20T08:45")
        var flightDetails = flight["details"] as! [String: Any]
        flightDetails["time_unknown"] = "no"
        flight["details"] = flightDetails
        var stay = AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T15:00", "2026-11-20T11:00")
        var stayDetails = stay["details"] as! [String: Any]
        stayDetails["time_unknown"] = "no"
        stay["details"] = stayDetails
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [flight, stay])])
        let subject = answers(at: AnswerFixtures.date("2026-11-18T20:00"))
        XCTAssertEqual(subject.nextFlight(copy).page, "#trip/1/flight/13")
        XCTAssertEqual(subject.tonight(copy).spoken, "Tonight you're staying at Hotel Example in Grand Junction. You check out Friday at 11 am.")
    }

    func testTheReaderSkipsABookingItCannotReadAndKeepsTheRest() throws {
        var broken = AnswerFixtures.flight(13, "2026-11-20T09:00", "2026-11-20T10:00")
        broken["start_zone"] = nil
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [broken, AnswerFixtures.flight(12, "2026-11-20T07:40", "2026-11-20T08:45")])])
        XCTAssertEqual(copy.trips.first?.bookings.map(\.id), [12])
    }

    func testACopySavedBeforeCitiesReadsWithNoCities() throws {
        var entry = AnswerFixtures.trip(1, "Trip", [AnswerFixtures.flight(12, "2026-11-20T07:40", "2026-11-20T08:45")])
        entry["cities"] = nil
        let copy = try saved([entry])
        XCTAssertEqual(copy.trips.first?.cities, [:])
    }

    func testTheReaderSeparatesNothingSavedFromAnUnreadableCopy() throws {
        let store = TripFixtures.store(at: root, now: savedTwoHoursAgo)
        XCTAssertEqual(SavedTripsReader.read(store, server: home), .nothingSaved)
        try store.save(AnswerFixtures.reply([]), version: 1, for: home)
        XCTAssertEqual(SavedTripsReader.read(store, server: home), .nothingSaved)
        try store.save(AnswerFixtures.reply([AnswerFixtures.trip(1, "Trip", [])], version: 2), version: 2, for: home)
        XCTAssertEqual(SavedTripsReader.read(store, server: home), .unreadable)
        XCTAssertEqual(SavedTripsReader.read(store, server: URL(string: "https://other.example.com")!), .nothingSaved)
    }

    // MARK: Wall-clock times

    func testWallClockReadsTheSavedFormat() {
        XCTAssertEqual(WallClock("2026-12-01T19:00"), WallClock(year: 2026, month: 12, day: 1, hour: 19, minute: 0))
        XCTAssertEqual(WallClock("2026-12-01T19:05:30"), WallClock(year: 2026, month: 12, day: 1, hour: 19, minute: 5))
        XCTAssertNil(WallClock("2026-13-01T19:00"))
        XCTAssertNil(WallClock("2026-12-01"))
        XCTAssertNil(WallClock("soon"))
    }

    func testWallClockCountsDaysAndFindsTheWeekday() {
        let wednesday = WallClock("2026-11-18T00:00")!
        XCTAssertEqual(wednesday.weekday, 3)
        XCTAssertEqual(WallClock("2026-11-20T00:00")!.dayNumber - wednesday.dayNumber, 2)
        XCTAssertEqual(WallClock("2026-12-01T00:00")!.dayNumber - wednesday.dayNumber, 13)
        XCTAssertEqual(WallClock("1970-01-01T00:00")!.dayNumber, 0)
        XCTAssertEqual(WallClock("2028-03-01T00:00")!.dayNumber - WallClock("2028-02-28T00:00")!.dayNumber, 2)
    }

    // MARK: Next flight

    private let denverGJ = [AnswerFixtures.flight(13, "2026-11-20T07:40", "2026-11-20T08:45")]

    func testNextFlightLaterThisWeekSpeaksTheCitiesTheDayAndTheTimeInLocalTime() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Grand Junction", denverGJ)])
        let answer = answers(at: wednesday5am).nextFlight(copy)
        XCTAssertEqual(answer.kind, .flight)
        XCTAssertEqual(answer.spoken, "Your next flight leaves Denver for Grand Junction on Friday at 7:40 am, local time.")
        XCTAssertEqual(answer.page, "#trip/1/flight/13")
        let card = try XCTUnwrap(answer.card)
        XCTAssertEqual(card.kind, .flight)
        XCTAssertEqual(card.eyebrow, "Next flight · Fri Nov 20")
        XCTAssertEqual(card.title, "EA 214")
        XCTAssertEqual(card.chip, AnswerCard.Chip(text: "Booked times", tone: .quiet))
        XCTAssertEqual(card.from, AnswerCard.Stop(code: "DEN", city: "Denver", time: "7:40 am", zone: TimeZone(identifier: AnswerFixtures.denver)!.abbreviation(for: AnswerFixtures.date("2026-11-20T07:40"))!))
        XCTAssertEqual(card.to?.code, "GJT")
        XCTAssertEqual(card.to?.city, "Grand Junction")
        XCTAssertEqual(card.to?.time, "8:45 am")
        XCTAssertEqual(card.footer, "Trip: Grand Junction")
        XCTAssertEqual(card.saved, "Saved 2 hours ago")
    }

    func testAFlightTodayAddsHowLongUntilItLeaves() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Grand Junction", [AnswerFixtures.flight(13, "2026-11-18T07:40", "2026-11-18T08:45")])])
        let answer = answers(at: wednesday5am).nextFlight(copy)
        XCTAssertEqual(answer.spoken, "Your flight leaves Denver for Grand Junction today at 7:40 am, local time, in 2 hours.")
        XCTAssertEqual(answer.card?.eyebrow, "Next flight · Today")
        XCTAssertEqual(answer.card?.chip, AnswerCard.Chip(text: "In 2 h", tone: .info))
        let soon = answers(at: AnswerFixtures.date("2026-11-18T07:00")).nextFlight(copy)
        XCTAssertEqual(soon.spoken, "Your flight leaves Denver for Grand Junction today at 7:40 am, local time, in 40 minutes.")
        XCTAssertEqual(soon.card?.chip.text, "In 40 min")
    }

    func testAFlightTomorrowSaysTomorrow() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Grand Junction", [AnswerFixtures.flight(13, "2026-11-19T07:40", "2026-11-19T08:45")])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(copy).spoken,
                       "Your next flight leaves Denver for Grand Junction tomorrow at 7:40 am, local time.")
    }

    func testAFlightMoreThanAWeekOutSaysTheDate() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Grand Junction", [AnswerFixtures.flight(13, "2026-12-03T18:05", "2026-12-03T19:10")])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(copy).spoken,
                       "Your next flight leaves Denver for Grand Junction on December 3 at 6:05 pm, local time.")
    }

    func testTheTimeIsSpokenWithTheMinutesOnlyWhenThereAreSome() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.flight(13, "2026-11-20T12:00", "2026-11-20T13:00")])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(copy).spoken, "Your next flight leaves Denver for Grand Junction on Friday at 12 pm, local time.")
        let night = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.flight(13, "2026-11-20T00:05", "2026-11-20T01:00")])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(night).spoken, "Your next flight leaves Denver for Grand Junction on Friday at 12:05 am, local time.")
    }

    func testNextFlightSkipsCancelledUntimedAndDepartedFlights() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [
            AnswerFixtures.flight(10, "2026-11-17T07:40", "2026-11-17T08:45"),
            AnswerFixtures.flight(11, "2026-11-18T06:00", "2026-11-18T07:00", status: "cancelled"),
            AnswerFixtures.flight(12, "2026-11-18T06:30", "2026-11-18T07:30", untimed: true),
            AnswerFixtures.flight(13, "2026-11-18T04:59", "2026-11-18T06:00"),
            AnswerFixtures.flight(14, "2026-11-20T07:40", "2026-11-20T08:45"),
        ])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(copy).page, "#trip/1/flight/14")
    }

    func testNextFlightIsTheEarliestOnAnySavedTripWhoeverIsOnIt() throws {
        let later = AnswerFixtures.trip(1, "Later", [AnswerFixtures.flight(30, "2026-11-24T07:40", "2026-11-24T08:45")])
        let sooner = AnswerFixtures.trip(2, "Someone else's", [AnswerFixtures.flight(20, "2026-11-19T18:05", "2026-11-19T23:52", to: "JFK", number: "EA 88", endZone: AnswerFixtures.newYork)])
        let answer = answers(at: wednesday5am).nextFlight(try saved([later, sooner]))
        XCTAssertEqual(answer.page, "#trip/2/flight/20")
        XCTAssertEqual(answer.spoken, "Your next flight leaves Denver for New York tomorrow at 6:05 pm, local time.")
    }

    func testTheArrivalIsShownInItsOwnZoneAndNotConverted() throws {
        let copy = try saved([AnswerFixtures.trip(2, "Trip", [AnswerFixtures.flight(20, "2026-11-19T18:05", "2026-11-19T23:52", to: "JFK", number: "EA 88", endZone: AnswerFixtures.newYork)])])
        let card = try XCTUnwrap(answers(at: wednesday5am).nextFlight(copy).card)
        XCTAssertEqual(card.from?.time, "6:05 pm")
        XCTAssertEqual(card.to?.time, "11:52 pm")
        XCTAssertEqual(card.to?.city, "New York")
        XCTAssertEqual(card.to?.zone, TimeZone(identifier: AnswerFixtures.newYork)!.abbreviation(for: AnswerFixtures.date("2026-11-19T23:52", AnswerFixtures.newYork)))
        XCTAssertNotEqual(card.from?.zone, card.to?.zone)
    }

    func testTheDayIsTheDayAtTheDepartureAirportNotOnThePhone() throws {
        // 14:00 UTC on Nov 18 is already 03:00 on Nov 19 in Auckland, where the flight leaves.
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.flight(13, "2026-11-19T08:00", "2026-11-18T22:00", from: "AKL", to: "LAX", startZone: AnswerFixtures.auckland, endZone: "America/Los_Angeles")], cities: ["AKL": "Auckland", "LAX": "Los Angeles"])])
        let answer = answers(at: TripFixtures.utc.date(from: DateComponents(year: 2026, month: 11, day: 18, hour: 14))!).nextFlight(copy)
        XCTAssertEqual(answer.spoken, "Your flight leaves Auckland for Los Angeles today at 8 am, local time, in 5 hours.")
        XCTAssertEqual(answer.card?.to?.time, "10:00 pm")
    }

    func testACopySavedBeforeCitiesSpeaksTheFlightNumber() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", denverGJ, cities: [:])])
        let answer = answers(at: wednesday5am).nextFlight(copy)
        XCTAssertEqual(answer.spoken, "Your next flight, EA 214, leaves Friday at 7:40 am, local time.")
        XCTAssertNil(answer.card?.from?.city)
        XCTAssertEqual(answer.card?.from?.code, "DEN")
        let today = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.flight(13, "2026-11-18T07:40", "2026-11-18T08:45")], cities: [:])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(today).spoken, "Your flight, EA 214, leaves today at 7:40 am, local time, in 2 hours.")
    }

    func testOneMissingCityAlsoFallsBackToTheFlightNumber() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", denverGJ, cities: ["DEN": "Denver"])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(copy).spoken, "Your next flight, EA 214, leaves Friday at 7:40 am, local time.")
    }

    func testNoUpcomingFlightIsSaid() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T15:00", "2026-11-20T11:00")])])
        XCTAssertEqual(answers(at: wednesday5am).nextFlight(copy), .noFlight)
        XCTAssertEqual(Answer.noFlight.spoken, "There's no upcoming flight in the trips saved on this iPhone.")
    }

    // MARK: Tonight's stay

    private let example = AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T15:00", "2026-11-20T11:00")
    private let later = AnswerFixtures.hotel(6, "Hotel Later", "2026-11-25T15:00", "2026-11-27T11:00", city: "Denver", address: "1 Later Street")

    func testTonightNamesTheHotelItsCityAndTheCheckOut() throws {
        let now = AnswerFixtures.date("2026-11-18T20:00")
        let answer = answers(at: now).tonight(try saved([AnswerFixtures.trip(3, "Trip", [example])], savedAt: now.addingTimeInterval(-7200)))
        XCTAssertEqual(answer.kind, .stay)
        XCTAssertEqual(answer.spoken, "Tonight you're staying at Hotel Example in Grand Junction. You check out Friday at 11 am.")
        XCTAssertEqual(answer.page, "#trip/3")
        let card = try XCTUnwrap(answer.card)
        XCTAssertEqual(card.kind, .stay)
        XCTAssertEqual(card.eyebrow, "Tonight")
        XCTAssertEqual(card.title, "Hotel Example")
        XCTAssertEqual(card.chip, AnswerCard.Chip(text: "Night 2 of 3", tone: .info))
        XCTAssertEqual(card.address, "100 Example Avenue, Grand Junction")
        XCTAssertEqual(card.checkIn, AnswerCard.Fact(day: "Tue Nov 17", time: "3:00 pm"))
        XCTAssertEqual(card.checkOut, AnswerCard.Fact(day: "Fri Nov 20", time: "11:00 am"))
        XCTAssertEqual(card.footer, "\(TimeZone(identifier: AnswerFixtures.denver)!.abbreviation(for: AnswerFixtures.date("2026-11-17T15:00"))!), the hotel's time")
        XCTAssertEqual(card.saved, "Saved 2 hours ago")
    }

    func testTheStreetAddressIsOnTheCardAndNeverSpoken() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example, later])])
        for question in [answers(at: AnswerFixtures.date("2026-11-18T20:00")).tonight(copy), answers(at: AnswerFixtures.date("2026-11-18T20:00")).checkOut(copy)] {
            XCTAssertNotNil(question.card?.address)
            XCTAssertFalse(question.spoken.contains("Example Avenue"))
        }
    }

    func testTheLastNightSaysTomorrowForTheCheckOut() throws {
        let now = AnswerFixtures.date("2026-11-19T22:00")
        let answer = answers(at: now).tonight(try saved([AnswerFixtures.trip(3, "Trip", [example])], savedAt: now.addingTimeInterval(-7200)))
        XCTAssertEqual(answer.spoken, "Tonight you're staying at Hotel Example in Grand Junction. You check out tomorrow at 11 am.")
        XCTAssertEqual(answer.card?.chip.text, "Night 3 of 3")
    }

    func testTonightIsTonightInTheHotelsZoneNotThePhones() throws {
        // 05:00 UTC on Nov 20 is 22:00 on Nov 19 in Denver: the last night, though on the phone it is already check-out day.
        let answer = answers(at: TripFixtures.utc.date(from: DateComponents(year: 2026, month: 11, day: 20, hour: 5))!).tonight(try saved([AnswerFixtures.trip(3, "Trip", [example])]))
        XCTAssertEqual(answer.kind, .stay)
        XCTAssertEqual(answer.card?.eyebrow, "Tonight")
        XCTAssertEqual(answer.spoken, "Tonight you're staying at Hotel Example in Grand Junction. You check out tomorrow at 11 am.")
    }

    func testOnCheckOutMorningTonightIsTheNextStay() throws {
        let now = AnswerFixtures.date("2026-11-20T08:00")
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example, later])], savedAt: now.addingTimeInterval(-7200))
        let answer = answers(at: now).tonight(copy)
        XCTAssertEqual(answer.spoken, "You have no stay tonight. Your next stay is Hotel Later, from Wednesday.")
        XCTAssertEqual(answer.card?.eyebrow, "Next stay")
        XCTAssertEqual(answer.card?.title, "Hotel Later")
        XCTAssertEqual(answer.card?.chip, AnswerCard.Chip(text: "2 nights", tone: .info))
    }

    func testANextStayMoreThanAWeekOutIsSpokenWithItsDate() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [later])])
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-18T20:00")).tonight(copy).spoken,
                       "You have no stay tonight. Your next stay is Hotel Later, from November 25.")
    }

    func testTonightWithNoLaterStayIsNone() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example])])
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-20T08:00")).tonight(copy), .noStayTonight)
        XCTAssertEqual(Answer.noStayTonight.spoken, "There's no stay tonight or later in the trips saved on this iPhone.")
    }

    func testACancelledStayIsNeverAnswered() throws {
        let cancelled = AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T15:00", "2026-11-20T11:00", status: "cancelled")
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [cancelled])])
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-18T20:00")).tonight(copy), .noStayTonight)
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-18T20:00")).checkOut(copy), .noStayToCheckOutOf)
    }

    func testAStayWithNoCityIsSpokenWithoutOne() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T15:00", "2026-11-20T11:00", city: nil, address: nil)])])
        let answer = answers(at: AnswerFixtures.date("2026-11-18T20:00")).tonight(copy)
        XCTAssertEqual(answer.spoken, "Tonight you're staying at Hotel Example. You check out Friday at 11 am.")
        XCTAssertNil(answer.card?.address)
    }

    func testAStayWithNoTimesSaysTheDayOnly() throws {
        let untimed = AnswerFixtures.hotel(5, "Hotel Example", "2026-11-17T00:00", "2026-11-20T00:00", untimed: true)
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [untimed])])
        let tonight = answers(at: AnswerFixtures.date("2026-11-18T20:00")).tonight(copy)
        XCTAssertEqual(tonight.spoken, "Tonight you're staying at Hotel Example in Grand Junction. You check out Friday.")
        XCTAssertNil(tonight.card?.checkOut?.time)
        let out = answers(at: AnswerFixtures.date("2026-11-20T15:00")).checkOut(copy)
        XCTAssertEqual(out.spoken, "You check out of Hotel Example today.")
    }

    // MARK: Check-out

    func testCheckOutLaterAnswersWithTheDayAndTime() throws {
        let now = AnswerFixtures.date("2026-11-18T20:00")
        let answer = answers(at: now).checkOut(try saved([AnswerFixtures.trip(3, "Trip", [example])], savedAt: now.addingTimeInterval(-7200)))
        XCTAssertEqual(answer.spoken, "You check out of Hotel Example on Friday at 11 am.")
        XCTAssertEqual(answer.card?.eyebrow, "Check-out Friday")
        XCTAssertEqual(answer.card?.chip.text, "Night 2 of 3")
        XCTAssertEqual(answer.page, "#trip/3")
    }

    func testAt8AmOnCheckOutMorningItIsStillThatStay() throws {
        let now = AnswerFixtures.date("2026-11-20T08:00")
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example, later])], savedAt: now.addingTimeInterval(-7200))
        let answer = answers(at: now).checkOut(copy)
        XCTAssertEqual(answer.spoken, "You check out of Hotel Example today at 11 am.")
        XCTAssertEqual(answer.card?.eyebrow, "Check-out today")
        XCTAssertEqual(answer.card?.title, "Hotel Example")
        XCTAssertEqual(answer.card?.chip, AnswerCard.Chip(text: "Check-out day", tone: .info))
        XCTAssertEqual(answer.card?.checkOut, AnswerCard.Fact(day: "Fri Nov 20", time: "11:00 am"))
    }

    func testAt1059AmItIsStillThatStayAndAt11AmItIsNot() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example, later])])
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-20T10:59")).checkOut(copy).spoken, "You check out of Hotel Example today at 11 am.")
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-20T11:00")).checkOut(copy).card?.title, "Hotel Later")
    }

    func testAt1101AmItIsTheNextSavedStayOrNone() throws {
        let both = try saved([AnswerFixtures.trip(3, "Trip", [example, later])])
        let next = answers(at: AnswerFixtures.date("2026-11-20T11:01")).checkOut(both)
        XCTAssertEqual(next.spoken, "You're not checked in anywhere right now. Your next stay is Hotel Later, from Wednesday.")
        XCTAssertEqual(next.card?.title, "Hotel Later")
        let alone = try saved([AnswerFixtures.trip(3, "Trip", [example])])
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-20T11:01")).checkOut(alone), .noStayToCheckOutOf)
        XCTAssertEqual(Answer.noStayToCheckOutOf.spoken, "There's no stay to check out of in the trips saved on this iPhone.")
    }

    func testTheTonightQuestionKeepsItsOwnRuleOnCheckOutMorning() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example])])
        let at8 = answers(at: AnswerFixtures.date("2026-11-20T08:00"))
        XCTAssertEqual(at8.checkOut(copy).kind, .stay)
        XCTAssertEqual(at8.tonight(copy), .noStayTonight)
    }

    func testBeforeCheckInItIsTheNextStay() throws {
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example])])
        let answer = answers(at: AnswerFixtures.date("2026-11-16T10:00")).checkOut(copy)
        XCTAssertEqual(answer.spoken, "You're not checked in anywhere right now. Your next stay is Hotel Example, from tomorrow.")
    }

    func testWithTwoUnderWayTheOneThatChecksOutFirstIsAnswered() throws {
        let early = AnswerFixtures.hotel(7, "Hotel Early", "2026-11-18T15:00", "2026-11-19T23:30", city: "Denver")
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example]), AnswerFixtures.trip(4, "Other", [early])])
        let answer = answers(at: AnswerFixtures.date("2026-11-19T22:00")).checkOut(copy)
        XCTAssertEqual(answer.spoken, "You check out of Hotel Early today at 11:30 pm.")
        XCTAssertEqual(answer.page, "#trip/4")
    }

    func testAStayEndingTodayAndAnotherStartingTodayAnswersWithTheOneEnding() throws {
        let starting = AnswerFixtures.hotel(8, "Hotel Starting", "2026-11-20T15:00", "2026-11-22T11:00", city: "Denver")
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example, starting])])
        XCTAssertEqual(answers(at: AnswerFixtures.date("2026-11-20T08:00")).checkOut(copy).card?.title, "Hotel Example")
    }

    func testCheckOutUsesTheHotelsZoneNotThePhones() throws {
        // 17:00 UTC on Nov 20 is 10:00 in Denver: an hour before the 11 am check-out there, though it is past 11 am in UTC.
        let at = TripFixtures.utc.date(from: DateComponents(year: 2026, month: 11, day: 20, hour: 17))!
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example])])
        XCTAssertEqual(answers(at: at).checkOut(copy).spoken, "You check out of Hotel Example today at 11 am.")
    }

    // MARK: The age of the copy

    func testTheCardSaysHowOldTheCopyIsAndTheSpokenAnswerDoesNot() throws {
        let now = wednesday5am
        func age(_ seconds: TimeInterval) throws -> Answer {
            answers(at: now).nextFlight(try saved([AnswerFixtures.trip(1, "Trip", denverGJ)], savedAt: now.addingTimeInterval(-seconds)))
        }
        XCTAssertEqual(try age(20).card?.saved, "Saved just now")
        XCTAssertEqual(try age(20 * 60).card?.saved, "Saved 20 min ago")
        XCTAssertEqual(try age(3600).card?.saved, "Saved 1 hour ago")
        XCTAssertEqual(try age(2 * 3600).card?.saved, "Saved 2 hours ago")
        let old = try age(3 * 24 * 3600)
        XCTAssertEqual(old.card?.saved, "Saved 3 days ago · open Waypoint to update")
        XCTAssertEqual(old.card?.chip, AnswerCard.Chip(text: "Old copy", tone: .warn))
        XCTAssertEqual(old.spoken, "Your next flight leaves Denver for Grand Junction on Friday at 7:40 am, local time.")
        XCTAssertEqual(try age(24 * 3600 - 60).card?.chip.text, "Booked times")
    }

    func testAnOldCopyTurnsAStayChipToOldCopyToo() throws {
        let now = AnswerFixtures.date("2026-11-18T20:00")
        let copy = try saved([AnswerFixtures.trip(3, "Trip", [example])], savedAt: now.addingTimeInterval(-2 * 24 * 3600))
        XCTAssertEqual(answers(at: now).tonight(copy).card?.chip, AnswerCard.Chip(text: "Old copy", tone: .warn))
    }

    // MARK: Parking

    private let lotExample = AnswerFixtures.parking(40, "Lot Example", "2026-11-17T09:00", "2026-11-20T18:00")

    func testTheCurrentParkingBookingOpensItsTripAndSaysOnlyTheLot() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Grand Junction", denverGJ + [lotExample])])
        let answer = answers(at: wednesday5am).parking(copy)
        XCTAssertEqual(answer.kind, .parking)
        XCTAssertEqual(answer.spoken, "Opening your parking at Lot Example.")
        XCTAssertEqual(answer.page, "#trip/1")
        XCTAssertNil(answer.card)
    }

    func testTheLotIsTheOriginElseTheProviderElseParking() throws {
        let named = try saved([AnswerFixtures.trip(1, "Trip", [lotExample])])
        XCTAssertEqual(answers(at: wednesday5am).parking(named).spoken, "Opening your parking at Lot Example.")
        let provider = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.parking(41, nil, "2026-11-17T09:00", "2026-11-20T18:00")])])
        XCTAssertEqual(answers(at: wednesday5am).parking(provider).spoken, "Opening your parking at Provider Example.")
        let blank = try saved([AnswerFixtures.trip(1, "Trip", [AnswerFixtures.parking(42, "  ", "2026-11-17T09:00", "2026-11-20T18:00", provider: nil)])])
        XCTAssertEqual(answers(at: wednesday5am).parking(blank).spoken, "Opening your parking at Parking.")
    }

    func testBeforeEntryItIsTheNextBookingAndTheEarliestOneWins() throws {
        let sooner = AnswerFixtures.parking(43, "Lot Sooner", "2026-11-22T09:00", "2026-11-23T18:00")
        let furtherOut = AnswerFixtures.parking(44, "Lot Further", "2026-12-02T09:00", "2026-12-03T18:00")
        let copy = try saved([AnswerFixtures.trip(1, "Far", [furtherOut]), AnswerFixtures.trip(2, "Near", [sooner])])
        let answer = answers(at: wednesday5am).parking(copy)
        XCTAssertEqual(answer.spoken, "Opening your parking at Lot Sooner.")
        XCTAssertEqual(answer.page, "#trip/2")
    }

    func testTheCurrentBookingBeatsALaterOne() throws {
        let later = AnswerFixtures.parking(45, "Lot Later", "2026-11-22T09:00", "2026-11-23T18:00")
        let copy = try saved([AnswerFixtures.trip(1, "Later", [later]), AnswerFixtures.trip(2, "Now", [lotExample])])
        let answer = answers(at: wednesday5am).parking(copy)
        XCTAssertEqual(answer.spoken, "Opening your parking at Lot Example.")
        XCTAssertEqual(answer.page, "#trip/2")
    }

    func testWithTwoCurrentTheOneThatEndsFirstIsOpened() throws {
        let endsSooner = AnswerFixtures.parking(46, "Lot Ends First", "2026-11-18T01:00", "2026-11-19T18:00")
        let copy = try saved([AnswerFixtures.trip(1, "Long", [lotExample]), AnswerFixtures.trip(2, "Short", [endsSooner])])
        let answer = answers(at: wednesday5am).parking(copy)
        XCTAssertEqual(answer.spoken, "Opening your parking at Lot Ends First.")
        XCTAssertEqual(answer.page, "#trip/2")
    }

    func testEntryIsFromTheMomentItStartsAndExitIsUntilTheMomentItEnds() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [lotExample])])
        let atEntry = answers(at: AnswerFixtures.date("2026-11-17T09:00")).parking(copy)
        XCTAssertEqual(atEntry.spoken, "Opening your parking at Lot Example.")
        let justBefore = answers(at: AnswerFixtures.date("2026-11-17T08:59")).parking(copy)
        XCTAssertEqual(justBefore.spoken, "Opening your parking at Lot Example.", "before entry it is the next booking, the same one")
        let beforeExit = answers(at: AnswerFixtures.date("2026-11-20T17:59")).parking(copy)
        XCTAssertEqual(beforeExit.spoken, "Opening your parking at Lot Example.")
        let atExit = answers(at: AnswerFixtures.date("2026-11-20T18:00")).parking(copy)
        XCTAssertEqual(atExit, .noParking)
    }

    func testAfterExitItIsTheNextBookingOrNone() throws {
        let next = AnswerFixtures.parking(47, "Lot Next", "2026-12-04T09:00", "2026-12-05T18:00")
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [lotExample, next])])
        let after = answers(at: AnswerFixtures.date("2026-11-21T10:00")).parking(copy)
        XCTAssertEqual(after.spoken, "Opening your parking at Lot Next.")
        let past = answers(at: AnswerFixtures.date("2026-12-06T10:00")).parking(copy)
        XCTAssertEqual(past, .noParking)
    }

    func testACancelledBookingIsNeverOpened() throws {
        let cancelled = AnswerFixtures.parking(48, "Lot Cancelled", "2026-11-17T09:00", "2026-11-20T18:00", status: "cancelled")
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [cancelled])])
        XCTAssertEqual(answers(at: wednesday5am).parking(copy), .noParking)
        let withOther = try saved([AnswerFixtures.trip(1, "Trip", [cancelled, AnswerFixtures.parking(49, "Lot Next", "2026-11-24T09:00", "2026-11-25T18:00")])])
        XCTAssertEqual(answers(at: wednesday5am).parking(withOther).spoken, "Opening your parking at Lot Next.")
    }

    func testNoParkingAtAllSaysSo() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Grand Junction", denverGJ + [example])])
        let answer = answers(at: wednesday5am).parking(copy)
        XCTAssertEqual(answer, .noParking)
        XCTAssertEqual(answer.spoken, "There's no parking in the trips saved on this iPhone.")
        XCTAssertNil(answer.card)
        XCTAssertNil(answer.page)
    }

    func testABookingWithNoTimesIsCurrentFromItsFirstDayThroughItsLastDay() throws {
        let dated = AnswerFixtures.parking(50, "Lot Dated", "2026-11-18T00:00", "2026-11-20T00:00")
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [dated])])
        let first = answers(at: AnswerFixtures.date("2026-11-18T00:30")).parking(copy)
        XCTAssertEqual(first.page, "#trip/1")
        let last = answers(at: AnswerFixtures.date("2026-11-20T23:30")).parking(copy)
        XCTAssertEqual(last.spoken, "Opening your parking at Lot Dated.")
        let after = answers(at: AnswerFixtures.date("2026-11-21T00:30")).parking(copy)
        XCTAssertEqual(after, .noParking)
        let before = answers(at: AnswerFixtures.date("2026-11-17T23:30")).parking(copy)
        XCTAssertEqual(before.spoken, "Opening your parking at Lot Dated.", "the day before it is the next booking, the same one")
    }

    func testTheTimesAreTheLotsOwnZoneAndNotThePhones() throws {
        let lot = AnswerFixtures.parking(51, "Lot Eastern", "2026-11-18T07:00", "2026-11-18T09:00", zone: AnswerFixtures.newYork)
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [lot])])
        let during = answers(at: AnswerFixtures.date("2026-11-18T08:00", AnswerFixtures.newYork)).parking(copy)
        XCTAssertEqual(during.spoken, "Opening your parking at Lot Eastern.", "08:00 at the lot is 13:00 on the phone, after the booking's wall clock end")
    }

    func testNoPrivateValueReachesTheSpokenParkingAnswer() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", [lotExample, AnswerFixtures.parking(52, nil, "2026-12-04T09:00", "2026-12-05T18:00")])])
        var checked = 0
        for now in ["2026-11-16T10:00", "2026-11-18T05:00", "2026-11-21T10:00", "2026-12-04T10:00", "2026-12-06T10:00"].map({ AnswerFixtures.date($0) }) {
            let answer = answers(at: now).parking(copy)
            for text in AnswerFixtures.everything(in: answer) {
                for hidden in AnswerFixtures.canaries + ["1 Lot Road", "Grand Junction", "Trip"] {
                    XCTAssertFalse(text.contains(hidden), "\(hidden) found in \(text)")
                }
                checked += 1
            }
        }
        XCTAssertEqual(checked, 5)
    }

    // MARK: Never spoken, never on the card

    func testNoPrivateValueReachesAnySpokenAnswerOrCardField() throws {
        let copy = try saved([AnswerFixtures.trip(1, "Trip", denverGJ + [example, later])])
        let nows = ["2026-11-16T10:00", "2026-11-18T05:00", "2026-11-18T20:00", "2026-11-20T08:00", "2026-11-20T11:01"].map { AnswerFixtures.date($0) }
        var checked = 0
        for now in nows {
            let subject = answers(at: now)
            for answer in [subject.nextFlight(copy), subject.tonight(copy), subject.checkOut(copy)] {
                for text in AnswerFixtures.everything(in: answer) {
                    for canary in AnswerFixtures.canaries {
                        XCTAssertFalse(text.contains(canary), "\(canary) found in \(text)")
                    }
                    checked += 1
                }
            }
        }
        XCTAssertGreaterThan(checked, 20)
    }

    func testTheFixedAnswersHoldNoTripData() {
        for answer in [Answer.locked, .notSignedIn, .savingOff, .nothingSaved, .unreadable, .noFlight, .noStayTonight, .noStayToCheckOutOf, .noParking] {
            XCTAssertNil(answer.card)
            XCTAssertNil(answer.page)
        }
        XCTAssertEqual(Answer.locked.spoken, "Unlock your iPhone to see your trips in Waypoint.")
        XCTAssertEqual(Answer.notSignedIn.spoken, "Sign in to Waypoint on this iPhone first.")
        XCTAssertEqual(Answer.savingOff.spoken, "Saving trips is off on this iPhone. You can switch it on in Waypoint's Settings.")
        XCTAssertEqual(Answer.nothingSaved.spoken, "No trips are saved on this iPhone yet. Open Waypoint while you're online to save them.")
        XCTAssertEqual(Answer.unreadable.spoken, "Waypoint can't read the trips saved on this iPhone. Open the app to save them again.")
    }

    // MARK: The service

    private func service(server: URL?, unlocked: Bool = true, saving: Bool = true, now: Date? = nil) -> TripAnswerService {
        let suite = "trip-answers-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let settings = OfflineSettings(defaults: defaults)
        settings.set(saving)
        let clock = now ?? wednesday5am
        return TripAnswerService(currentServer: { server }, protectedDataAvailable: { unlocked },
                                 store: TripFixtures.store(at: root, now: savedTwoHoursAgo), settings: settings,
                                 now: { clock }, calendar: AnswerFixtures.phone)
    }

    private func save(_ trips: [[String: Any]], version: Int = 1) throws {
        try TripFixtures.store(at: root, now: savedTwoHoursAgo).save(AnswerFixtures.reply(trips, version: version), version: version, for: home)
    }

    func testAnAnswerFromTheSavedTrips() async throws {
        try save([AnswerFixtures.trip(1, "Grand Junction", denverGJ)])
        let answer = await service(server: home).answer(.nextFlight)
        XCTAssertEqual(answer.spoken, "Your next flight leaves Denver for Grand Junction on Friday at 7:40 am, local time.")
        let tonight = await service(server: home).answer(.tonight)
        XCTAssertEqual(tonight, .noStayTonight)
        let out = await service(server: home).answer(.checkOut)
        XCTAssertEqual(out, .noStayToCheckOutOf)
        let parked = await service(server: home).answer(.parking)
        XCTAssertEqual(parked, .noParking)
    }

    func testTheParkingQuestionAnswersFromTheSavedTrips() async throws {
        try save([AnswerFixtures.trip(1, "Grand Junction", denverGJ + [lotExample])])
        let answer = await service(server: home).answer(.parking)
        XCTAssertEqual(answer.spoken, "Opening your parking at Lot Example.")
        XCTAssertEqual(answer.page, "#trip/1")
    }

    func testALockedPhoneAnswersLockedWithoutReadingAnything() async throws {
        try save([AnswerFixtures.trip(1, "Grand Junction", denverGJ)])
        for question in [TripAnswerService.Question.nextFlight, .tonight, .checkOut, .parking] {
            let answer = await service(server: home, unlocked: false).answer(question)
            XCTAssertEqual(answer, .locked)
        }
        let after = await service(server: home).answer(.nextFlight)
        XCTAssertEqual(after.kind, .flight, "a locked read must not delete the copy")
    }

    func testNoSessionSavingOffNothingSavedAndAnUnreadableCopy() async throws {
        let signedOut = await service(server: nil).answer(.nextFlight)
        XCTAssertEqual(signedOut, .notSignedIn)
        let off = await service(server: home, saving: false).answer(.tonight)
        XCTAssertEqual(off, .savingOff)
        let nothing = await service(server: home).answer(.nextFlight)
        XCTAssertEqual(nothing, .nothingSaved)
        let signedOutParking = await service(server: nil).answer(.parking)
        XCTAssertEqual(signedOutParking, .notSignedIn)
        let offParking = await service(server: home, saving: false).answer(.parking)
        XCTAssertEqual(offParking, .savingOff)
        let nothingParking = await service(server: home).answer(.parking)
        XCTAssertEqual(nothingParking, .nothingSaved)
        try save([AnswerFixtures.trip(1, "Trip", denverGJ)], version: 2)
        let unreadable = await service(server: home).answer(.checkOut)
        XCTAssertEqual(unreadable, .unreadable)
        let unreadableParking = await service(server: home).answer(.parking)
        XCTAssertEqual(unreadableParking, .unreadable)
    }

    func testACopyForAnotherServerAnswersNothingSaved() async throws {
        try save([AnswerFixtures.trip(1, "Trip", denverGJ)])
        let answer = await service(server: URL(string: "https://other.example.com")!).answer(.nextFlight)
        XCTAssertEqual(answer, .nothingSaved)
    }

    // MARK: The intents

    func testEveryIntentRequiresAuthentication() {
        XCTAssertEqual(NextFlightIntent.authenticationPolicy, .requiresAuthentication)
        XCTAssertEqual(TonightStayIntent.authenticationPolicy, .requiresAuthentication)
        XCTAssertEqual(CheckOutIntent.authenticationPolicy, .requiresAuthentication)
        XCTAssertEqual(OpenParkingIntent.authenticationPolicy, .requiresAuthentication)
    }

    func testOnlyTheParkingIntentOpensTheApp() {
        XCTAssertTrue(OpenParkingIntent.openAppWhenRun)
        XCTAssertFalse(NextFlightIntent.openAppWhenRun)
        XCTAssertFalse(TonightStayIntent.openAppWhenRun)
        XCTAssertFalse(CheckOutIntent.openAppWhenRun)
    }

    func testRunningTheIntentsMakesNoRequest() async throws {
        try save([AnswerFixtures.trip(1, "Grand Junction", denverGJ + [example, lotExample])])
        let before = IntentRuntime.service
        let pages = IntentRuntime.pages
        defer {
            IntentRuntime.service = before
            IntentRuntime.pages = pages
            URLProtocol.unregisterClass(FailingProtocol.self)
        }
        IntentRuntime.service = service(server: home)
        IntentRuntime.pages = PendingPage()
        FailingProtocol.reset()
        URLProtocol.registerClass(FailingProtocol.self)
        _ = try await NextFlightIntent().perform()
        _ = try await TonightStayIntent().perform()
        _ = try await CheckOutIntent().perform()
        _ = try await OpenParkingIntent().perform()
        XCTAssertEqual(FailingProtocol.requests, 0)
    }

    func testAnIntentHoldsThePageItsCardOpens() async throws {
        try save([AnswerFixtures.trip(1, "Grand Junction", denverGJ)])
        let before = IntentRuntime.service
        let pages = IntentRuntime.pages
        defer {
            IntentRuntime.service = before
            IntentRuntime.pages = pages
        }
        IntentRuntime.service = service(server: home)
        let held = PendingPage()
        IntentRuntime.pages = held
        _ = try await NextFlightIntent().perform()
        XCTAssertEqual(held.take(), "#trip/1/flight/13")
        _ = try await TonightStayIntent().perform()
        XCTAssertNil(held.take(), "an answer with no card opens nothing")
    }

    func testTheParkingIntentHoldsTheTripPageOfTheBookingAndNothingWithNoParking() async throws {
        let before = IntentRuntime.service
        let pages = IntentRuntime.pages
        defer {
            IntentRuntime.service = before
            IntentRuntime.pages = pages
        }
        let held = PendingPage()
        IntentRuntime.pages = held
        try save([AnswerFixtures.trip(7, "Grand Junction", denverGJ + [lotExample])])
        IntentRuntime.service = service(server: home)
        _ = try await OpenParkingIntent().perform()
        XCTAssertEqual(held.take(), "#trip/7")
        try save([AnswerFixtures.trip(7, "Grand Junction", denverGJ)])
        _ = try await OpenParkingIntent().perform()
        XCTAssertNil(held.take(), "no parking opens no page")
    }
}

final class PendingPageTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)

    func testAPageIsTakenOnceAndOnlyWhileItIsFresh() {
        let pages = PendingPage()
        pages.hold("#trip/3", now: start)
        XCTAssertEqual(pages.take(now: start.addingTimeInterval(60)), "#trip/3")
        XCTAssertNil(pages.take(now: start.addingTimeInterval(61)), "it is used once")
        pages.hold("#trip/3/flight/12", now: start)
        XCTAssertNil(pages.take(now: start.addingTimeInterval(PendingPage.lifetime + 1)), "it expires")
    }

    func testOnlyTheTwoTripRoutesAreAccepted() {
        for good in ["#trip/3", "#trip/3/flight/12"] { XCTAssertTrue(PendingPage.isValid(good), good) }
        for bad in ["", "#trip/", "#trip/x", "#trip/3/", "#trip/3/flight/", "#trip/3'; alert(1)//", "javascript:alert(1)", "#settings", "https://example.com/#trip/3", "#trip/3\n"] {
            XCTAssertFalse(PendingPage.isValid(bad), bad)
        }
        let pages = PendingPage()
        pages.hold("#settings", now: start)
        XCTAssertNil(pages.take(now: start))
    }

    func testPeekingKeepsThePageUntilItIsCleared() {
        let pages = PendingPage()
        pages.hold("#trip/3", now: start)
        XCTAssertEqual(pages.peek(now: start.addingTimeInterval(10)), "#trip/3")
        XCTAssertEqual(pages.peek(now: start.addingTimeInterval(20)), "#trip/3")
        XCTAssertNil(pages.peek(now: start.addingTimeInterval(PendingPage.lifetime + 1)), "it expires")
        pages.clear()
        XCTAssertNil(pages.peek(now: start.addingTimeInterval(20)))
        XCTAssertNil(pages.take(now: start.addingTimeInterval(20)))
    }

    func testTheScriptOpensOnlyATripRoute() {
        XCTAssertEqual(PendingPage.script(for: "#trip/3"), "window.location.hash = '#trip/3'")
        XCTAssertEqual(PendingPage.script(for: "#trip/3/flight/12"), "window.location.hash = '#trip/3/flight/12'")
        XCTAssertNil(PendingPage.script(for: "#trip/3'; alert(1)//"))
        XCTAssertNil(PendingPage.script(for: "#settings"))
    }

    func testAColdStartThatFallsBackKeepsThePageUntilItIsApplied() {
        let pages = PendingPage()
        pages.hold("#trip/3", now: start)
        XCTAssertEqual(pages.peek(now: start.addingTimeInterval(5)), "#trip/3", "read for the launch address, not used up")
        XCTAssertEqual(pages.peek(now: start.addingTimeInterval(15)), "#trip/3", "still there for the cached page")
        pages.clear()
        XCTAssertNil(pages.peek(now: start.addingTimeInterval(16)))
    }

    func testHoldingNothingClearsWhatWasHeld() {
        let pages = PendingPage()
        pages.hold("#trip/3", now: start)
        pages.hold(nil, now: start)
        XCTAssertNil(pages.take(now: start))
    }
}
