import AppIntents
import Foundation

/// What a read of the saved trips gives an intent: the trips, or the fixed answer that says why there are none to read.
enum TripsRead: Equatable {
    case trips([SavedTrip])
    case fixed(Answer)
}

extension TripAnswerService {
    /// The saved trips of the server in `ServerSession`, under the same checks as `answer(_:)`: nothing is read while the phone is
    /// locked, with no session or with saving off. No network request.
    func readTrips() async -> TripsRead {
        guard await protectedDataAvailable() else { return .fixed(.locked) }
        guard let server = await currentServer() else { return .fixed(.notSignedIn) }
        guard settings.isOn else { return .fixed(.savingOff) }
        switch SavedTripsReader.read(store, server: server) {
        case .nothingSaved: return .fixed(.nothingSaved)
        case .unreadable: return .fixed(.unreadable)
        case .copy(let copy): return .trips(copy.trips)
        }
    }
}

/// A saved trip as Siri and Shortcuts know it: its place (the destination, else the name) and its dates. Nothing of a booking.
struct TripEntity: AppEntity, Equatable {
    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Trip")
    static var defaultQuery = TripEntityQuery()

    let id: Int
    let place: String
    let dates: String?

    init(id: Int, place: String, dates: String?) {
        self.id = id
        self.place = place
        self.dates = dates
    }

    init(_ trip: SavedTrip) {
        self.init(id: trip.id, place: TripPlaces.place(of: trip), dates: TripPlaces.dates(of: trip))
    }

    var displayRepresentation: DisplayRepresentation {
        if let dates { return DisplayRepresentation(title: "\(place)", subtitle: "\(dates)") }
        return DisplayRepresentation(title: "\(place)")
    }
}

/// Answers only from the saved copy, so after a purge it is empty. `suggestedEntities()` is what
/// `updateAppShortcutParameters()` gives the system as the places a phrase can name.
struct TripEntityQuery: EntityStringQuery {
    func entities(for identifiers: [Int]) async throws -> [TripEntity] {
        guard case .trips(let trips) = await IntentRuntime.service.readTrips() else { return [] }
        return TripPlaces.entities(in: trips).filter { identifiers.contains($0.id) }
    }

    func entities(matching string: String) async throws -> [TripEntity] {
        guard case .trips(let trips) = await IntentRuntime.service.readTrips() else { return [] }
        return TripPlaces.matching(string, in: trips).map(TripEntity.init)
    }

    func suggestedEntities() async throws -> [TripEntity] {
        guard case .trips(let trips) = await IntentRuntime.service.readTrips() else { return [] }
        return TripPlaces.entities(in: trips)
    }
}

/// What Siri says and the page it opens for "open my trip". A pure function of the entity that was picked and the saved trips now.
struct OpenTripAnswer: Equatable {
    let spoken: String
    let page: String?
}

/// Pure rules for naming a saved trip by voice. Only a trip's destination, name and dates are used.
enum TripPlaces {
    private static let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    private static func trimmed(_ text: String?) -> String? {
        guard let text = text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return text
    }

    /// The destination, else the name.
    static func place(of trip: SavedTrip) -> String {
        trimmed(trip.destination) ?? trimmed(trip.name) ?? trip.name
    }

    /// "Dec 1 to Dec 8", "Dec 1" for one day or with no end, nil with no start.
    static func dates(of trip: SavedTrip) -> String? {
        guard let start = day(trip.startDate) else { return nil }
        guard let end = day(trip.endDate), end != start else { return start }
        return "\(start) to \(end)"
    }

    private static func day(_ text: String?) -> String? {
        guard let text else { return nil }
        let parts = text.prefix(10).split(separator: "-", omittingEmptySubsequences: false).map { Int($0) }
        guard parts.count == 3, let month = parts[1], let day = parts[2], (1...12).contains(month), (1...31).contains(day) else { return nil }
        return "\(months[month - 1]) \(day)"
    }

    /// Every saved trip, soonest first, as the places a phrase can name. Two trips to one place are two entities, told apart by dates.
    static func entities(in trips: [SavedTrip]) -> [TripEntity] {
        trips.sorted { ($0.startDate ?? "", $0.id) < ($1.startDate ?? "", $1.id) }.map(TripEntity.init)
    }

    private static func normalized(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The saved trips whose destination or name is what was said: an exact match if there is one, else those that contain it.
    static func matching(_ said: String, in trips: [SavedTrip]) -> [SavedTrip] {
        let wanted = normalized(said)
        guard !wanted.isEmpty else { return [] }
        let ordered = trips.sorted { ($0.startDate ?? "", $0.id) < ($1.startDate ?? "", $1.id) }
        func fields(_ trip: SavedTrip) -> [String] {
            [trip.destination, trip.name].compactMap { $0 }.map(normalized).filter { !$0.isEmpty }
        }
        let exact = ordered.filter { fields($0).contains(wanted) }
        if !exact.isEmpty { return exact }
        return ordered.filter { trip in fields(trip).contains { $0.contains(wanted) } }
    }

    /// "Opening your trip to Grand Junction." with `#trip/{id}`, or, when the trip is no longer saved, "There's no trip to
    /// Lisbon saved on this iPhone. Opening Waypoint." with no page, so the app opens on Upcoming.
    static func open(_ picked: TripEntity, in read: TripsRead) -> OpenTripAnswer {
        switch read {
        case .trips(let trips):
            if let trip = trips.first(where: { $0.id == picked.id }) {
                return OpenTripAnswer(spoken: "Opening your trip to \(place(of: trip)).", page: "#trip/\(trip.id)")
            }
            return noTrip(picked.place)
        case .fixed(let answer):
            if answer.kind == .nothingSaved { return noTrip(picked.place) }
            return OpenTripAnswer(spoken: answer.spoken, page: nil)
        }
    }

    static func noTrip(_ place: String) -> OpenTripAnswer {
        OpenTripAnswer(spoken: "There's no trip to \(place) saved on this iPhone. Opening Waypoint.", page: nil)
    }
}
