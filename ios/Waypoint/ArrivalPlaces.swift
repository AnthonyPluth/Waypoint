import CoreLocation
import CryptoKit
import Foundation

/// A point on the earth, as looked up on the phone.
struct PlacePoint: Codable, Equatable {
    let latitude: Double
    let longitude: Double

    var isValid: Bool {
        (-90.0...90.0).contains(latitude) && (-180.0...180.0).contains(longitude)
    }
}

enum ArrivalKind: String, Codable, Equatable {
    case parking
    case rentalPickup
    case hotel

    /// Circle radius in metres (design README, point 5). A rental pickup known only by its airport's code gets the airport's circle.
    func radius(atAirport: Bool) -> Double {
        switch self {
        case .parking: return 250
        case .rentalPickup: return atAirport ? 2_000 : 300
        case .hotel: return 200
        }
    }
}

/// One watched booking: where it is and when it counts. Holds no name, address, code or confirmation number.
struct ArrivalPlace: Codable, Equatable {
    let segmentId: Int
    let tripId: Int
    let kind: ArrivalKind
    let latitude: Double
    let longitude: Double
    let radius: Double
    let opens: Date
    let closes: Date
}

/// A booking that qualifies, before it has a point.
struct ArrivalCandidate: Equatable {
    let segmentId: Int
    let tripId: Int
    let kind: ArrivalKind
    let address: String?
    let airport: PlacePoint?
    let opens: Date
    let closes: Date
}

/// Looks an address up. The only thing in the app that sends an address anywhere (to Apple, by `CLGeocoder`); it never gets the
/// phone's location.
protocol AddressGeocoding: Sendable {
    func point(for address: String) async -> PlacePoint?
}

struct LiveAddressGeocoder: AddressGeocoding {
    func point(for address: String) async -> PlacePoint? {
        let found = try? await CLGeocoder().geocodeAddressString(address)
        guard let coordinate = found?.first?.location?.coordinate else { return nil }
        let point = PlacePoint(latitude: coordinate.latitude, longitude: coordinate.longitude)
        return point.isValid ? point : nil
    }
}

/// Whether Waypoint may use the phone's location now: While Using or Always. There is no switch of Waypoint's own.
protocol LocationPermission: Sendable {
    var isAllowed: Bool { get }
}

struct LiveLocationPermission: LocationPermission {
    var isAllowed: Bool {
        let status = CLLocationManager().authorizationStatus
        return status == .authorizedWhenInUse || status == .authorizedAlways
    }
}

/// Finds the place of each booking on the saved trips that the arrival feature may watch (design `docs/design/arrival-codes/`, points 4
/// and 5): parking, rental pickups and hotels, not cancelled, whose window hasn't ended. The point is `details.address` looked up with
/// Apple's geocoder on the phone (once per distinct address: the answer is cached by the SHA-256 of the address text), else, for a rental
/// pickup, its airport's coordinate from the saved trip's optional `airports` list. A booking with neither is not watched.
///
/// The result is one file inside the server's `OfflineStore` folder, `.complete` protected, carried through each save of the trips and
/// replaced after it, and deleted by every purge. Nothing is looked up without location permission, nothing is logged and no request is made
/// but the geocoder's.
actor ArrivalPlaces {
    static let fileVersion = 1
    static let parkingLead: TimeInterval = 2 * 3600
    static let rentalLead: TimeInterval = 2 * 3600
    static let rentalTail: TimeInterval = 4 * 3600
    static let hotelLead: TimeInterval = 3 * 3600

    /// A cached lookup, with the saved trips that use it, so `OfflineStore` can drop it when they expire.
    private struct CachedPoint: Codable {
        let latitude: Double
        let longitude: Double
        let tripIds: [Int]

        var point: PlacePoint { PlacePoint(latitude: latitude, longitude: longitude) }
    }

    private struct PlacesFile: Codable {
        let version: Int
        let geocoded: [String: CachedPoint]
        let places: [ArrivalPlace]
    }

    private let store: OfflineStore
    private let geocoder: AddressGeocoding
    private let permission: LocationPermission
    private let calendar: Calendar
    private let now: @Sendable () -> Date

    init(store: OfflineStore = .shared,
         geocoder: AddressGeocoding = LiveAddressGeocoder(),
         permission: LocationPermission = LiveLocationPermission(),
         calendar: Calendar = .current,
         now: @escaping @Sendable () -> Date = { Date() }) {
        self.store = store
        self.geocoder = geocoder
        self.permission = permission
        self.calendar = calendar
        self.now = now
    }

    /// Whether the saved copy holds a booking that qualifies, with or without a point. Needs no location permission and looks nothing up.
    func qualifies(server: URL) -> Bool {
        guard let snapshot = store.load(server: server), snapshot.version == OfflineSync.supportedVersion else { return false }
        return !Self.candidates(in: snapshot.json, now: now(), calendar: calendar).isEmpty
    }

    /// The places found by the last `refresh`, soonest window first, without a lookup. Only those of a trip that is still saved: reading
    /// the saved trips first drops an expired trip's places from the file too (`OfflineStore`).
    func places(server: URL) -> [ArrivalPlace] {
        guard let snapshot = store.load(server: server), snapshot.version == OfflineSync.supportedVersion,
              let file = readFile(server: server) else { return [] }
        let saved = Self.savedTripIds(in: snapshot.json)
        return file.places.filter { saved.contains($0.tripId) }
    }

    private static func savedTripIds(in json: Data) -> Set<Int> {
        guard let root = try? JSONDecoder().decode(ArrivalRoot.self, from: json) else { return [] }
        return Set(root.trips.compactMap(\.value).map(\.id))
    }

    /// Looks up the qualifying bookings' places and replaces the file. Without location permission it looks nothing up and deletes the
    /// file. Stops without writing when the task is cancelled (a purge) or when the permission goes while it runs.
    @discardableResult
    func refresh(server: URL) async -> [ArrivalPlace] {
        guard permission.isAllowed else {
            store.deletePlaces(server: server)
            return []
        }
        guard let snapshot = store.load(server: server), snapshot.version == OfflineSync.supportedVersion else { return [] }
        let wanted = Self.candidates(in: snapshot.json, now: now(), calendar: calendar)
        let earlier = readFile(server: server)?.geocoded ?? [:]
        var geocoded: [String: PlacePoint] = [:]
        var users: [String: Set<Int>] = [:]
        var missed: Set<String> = []
        var found: [ArrivalPlace] = []
        for candidate in wanted {
            var point: PlacePoint?
            var atAirport = false
            if let address = Self.clean(candidate.address) {
                let key = Self.key(address)
                if let known = geocoded[key] ?? earlier[key]?.point {
                    geocoded[key] = known
                    users[key, default: []].insert(candidate.tripId)
                    point = known
                } else if !missed.contains(key) {
                    if Task.isCancelled { return [] }
                    // Permission is checked before every request: once it goes, nothing more is sent to Apple.
                    guard permission.isAllowed else {
                        store.deletePlaces(server: server)
                        return []
                    }
                    if let looked = await geocoder.point(for: address), looked.isValid {
                        geocoded[key] = looked
                        users[key, default: []].insert(candidate.tripId)
                        point = looked
                    } else {
                        missed.insert(key)
                    }
                }
            }
            if point == nil, let airport = candidate.airport {
                point = airport
                atAirport = true
            }
            guard let place = point else { continue }
            found.append(ArrivalPlace(segmentId: candidate.segmentId, tripId: candidate.tripId, kind: candidate.kind,
                                      latitude: place.latitude, longitude: place.longitude,
                                      radius: candidate.kind.radius(atAirport: atAirport),
                                      opens: candidate.opens, closes: candidate.closes))
        }
        guard !Task.isCancelled else { return [] }
        guard permission.isAllowed else {
            store.deletePlaces(server: server)
            return []
        }
        var cached: [String: CachedPoint] = [:]
        for (key, looked) in geocoded {
            cached[key] = CachedPoint(latitude: looked.latitude, longitude: looked.longitude, tripIds: (users[key] ?? []).sorted())
        }
        let file = PlacesFile(version: Self.fileVersion, geocoded: cached, places: found)
        if let data = try? Self.encoder.encode(file) {
            try? store.savePlaces(data, for: server)
        }
        return found
    }

    // MARK: The saved file

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }()

    private func readFile(server: URL) -> PlacesFile? {
        guard let data = store.loadPlaces(server: server) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let file = try? decoder.decode(PlacesFile.self, from: data), file.version == Self.fileVersion else { return nil }
        return file
    }

    /// The cache key of an address: the SHA-256 of its trimmed text.
    static func key(_ address: String) -> String {
        SHA256.hash(data: Data(address.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func clean(_ text: String?) -> String? {
        guard let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else { return nil }
        return trimmed
    }

    // MARK: Which bookings qualify

    /// The bookings of the saved copy that qualify, soonest window first: parking, car pickups and hotels, not cancelled, whose window
    /// hasn't ended at `now`. Pure: no lookup, no file.
    static func candidates(in json: Data, now: Date, calendar: Calendar) -> [ArrivalCandidate] {
        guard let root = try? JSONDecoder().decode(ArrivalRoot.self, from: json) else { return [] }
        var found: [ArrivalCandidate] = []
        for trip in root.trips.compactMap(\.value) {
            for booking in trip.bookings where !booking.isCancelled {
                guard let kind = Self.kind(of: booking.kind),
                      let span = Self.window(of: booking, as: kind, fallback: calendar.timeZone),
                      span.closes > now else { continue }
                let airport = kind == .rentalPickup ? booking.airportCode.flatMap { trip.airports[$0] } : nil
                found.append(ArrivalCandidate(segmentId: booking.id, tripId: trip.id, kind: kind, address: booking.address,
                                              airport: airport, opens: span.opens, closes: span.closes))
            }
        }
        return found.sorted { ($0.opens, $0.tripId, $0.segmentId) < ($1.opens, $1.tripId, $1.segmentId) }
    }

    private static func kind(of text: String) -> ArrivalKind? {
        switch text {
        case "parking": return .parking
        case "car": return .rentalPickup
        case "hotel": return .hotel
        default: return nil
        }
    }

    /// The window of design point 5, from the booking's own wall-clock times in its zones. A booking with no time (the flag, or
    /// midnight to midnight) has the whole day, or for parking every day to the end of the last, in place of the lead and tail times.
    private static func window(of booking: ArrivalSegment, as kind: ArrivalKind, fallback: TimeZone) -> (opens: Date, closes: Date)? {
        guard let start = WallClock(booking.startLocal) else { return nil }
        let startZone = zone(booking.startZone, fallback: fallback)
        guard let first = instant(start, in: startZone) else { return nil }
        let startCalendar = gregorian(startZone)
        let dayStart = startCalendar.startOfDay(for: first)
        guard let nextDay = startCalendar.date(byAdding: .day, value: 1, to: dayStart) else { return nil }
        let timed = !booking.hasNoTime
        let result: (opens: Date, closes: Date)
        switch kind {
        case .parking:
            guard let end = WallClock(booking.endLocal) else { return nil }
            let endZone = zone(booking.endZone, fallback: fallback)
            guard let leaves = instant(end, in: endZone) else { return nil }
            if timed {
                result = (first.addingTimeInterval(-parkingLead), leaves)
            } else {
                let endCalendar = gregorian(endZone)
                guard let after = endCalendar.date(byAdding: .day, value: 1, to: endCalendar.startOfDay(for: leaves)) else { return nil }
                result = (dayStart, after)
            }
        case .rentalPickup:
            result = timed ? (first.addingTimeInterval(-rentalLead), first.addingTimeInterval(rentalTail)) : (dayStart, nextDay)
        case .hotel:
            result = timed ? (max(first.addingTimeInterval(-hotelLead), dayStart), nextDay) : (dayStart, nextDay)
        }
        return result.closes > result.opens ? result : nil
    }

    private static func zone(_ identifier: String?, fallback: TimeZone) -> TimeZone {
        identifier.flatMap { TimeZone(identifier: $0) } ?? fallback
    }

    private static func gregorian(_ zone: TimeZone) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        return calendar
    }

    private static func instant(_ wall: WallClock, in zone: TimeZone) -> Date? {
        gregorian(zone).date(from: DateComponents(year: wall.year, month: wall.month, day: wall.day, hour: wall.hour, minute: wall.minute))
    }
}

// MARK: What is read of the saved copy

/// Only what the places need. Never decodes `confirmation`, `manage_url`, `travelers`, any other `details` key or `messages`.
private struct ArrivalTolerant<Value: Decodable>: Decodable {
    let value: Value?

    init(from decoder: Decoder) throws {
        value = try? Value(from: decoder)
    }
}

private struct ArrivalRoot: Decodable {
    let trips: [ArrivalTolerant<ArrivalTrip>]
}

private struct ArrivalAirport: Decodable {
    let code: String
    let point: PlacePoint

    private enum Keys: String, CodingKey {
        case code, latitude, longitude
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: Keys.self)
        code = try values.decode(String.self, forKey: .code).trimmingCharacters(in: .whitespaces).uppercased()
        point = PlacePoint(latitude: try values.decode(Double.self, forKey: .latitude),
                           longitude: try values.decode(Double.self, forKey: .longitude))
        guard !code.isEmpty, point.isValid else { throw DecodingError.dataCorruptedError(forKey: .code, in: values, debugDescription: "airport") }
    }
}

private struct ArrivalTrip: Decodable {
    let id: Int
    let bookings: [ArrivalSegment]
    /// The airports' coordinates by code. The optional `airports` list of a saved trip (#847); empty for a copy saved before it.
    let airports: [String: PlacePoint]

    private enum EntryKeys: String, CodingKey {
        case trip, airports
    }

    private enum TripKeys: String, CodingKey {
        case id, segments
    }

    init(from decoder: Decoder) throws {
        let entry = try decoder.container(keyedBy: EntryKeys.self)
        let trip = try entry.nestedContainer(keyedBy: TripKeys.self, forKey: .trip)
        id = try trip.decode(Int.self, forKey: .id)
        let segments: [ArrivalTolerant<ArrivalSegment>]? = try? trip.decodeIfPresent([ArrivalTolerant<ArrivalSegment>].self, forKey: .segments)
        bookings = (segments ?? []).compactMap(\.value)
        let listed: [ArrivalTolerant<ArrivalAirport>]? = try? entry.decodeIfPresent([ArrivalTolerant<ArrivalAirport>].self, forKey: .airports)
        var byCode: [String: PlacePoint] = [:]
        for airport in (listed ?? []).compactMap(\.value) where byCode[airport.code] == nil {
            byCode[airport.code] = airport.point
        }
        airports = byCode
    }
}

private struct ArrivalSegment: Decodable {
    let id: Int
    let kind: String
    let status: String
    let startLocal: String
    let startZone: String?
    let endLocal: String
    let endZone: String?
    let origin: String?
    let address: String?
    let timeUnknown: Bool

    private enum Keys: String, CodingKey {
        case id, kind, status, origin, details
        case startLocal = "start_local"
        case startZone = "start_zone"
        case endLocal = "end_local"
        case endZone = "end_zone"
    }

    private enum DetailKeys: String, CodingKey {
        case address
        case timeUnknown = "time_unknown"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: Keys.self)
        id = try values.decode(Int.self, forKey: .id)
        kind = try values.decode(String.self, forKey: .kind)
        status = try values.decodeIfPresent(String.self, forKey: .status) ?? "confirmed"
        startLocal = try values.decode(String.self, forKey: .startLocal)
        startZone = try? values.decodeIfPresent(String.self, forKey: .startZone)
        endLocal = (try? values.decodeIfPresent(String.self, forKey: .endLocal)) ?? startLocal
        endZone = try? values.decodeIfPresent(String.self, forKey: .endZone)
        origin = try? values.decodeIfPresent(String.self, forKey: .origin)
        if values.contains(.details), let details = try? values.nestedContainer(keyedBy: DetailKeys.self, forKey: .details) {
            address = try? details.decodeIfPresent(String.self, forKey: .address)
            let flag: String? = try? details.decodeIfPresent(String.self, forKey: .timeUnknown)
            timeUnknown = flag == "yes"   // exactly "yes", as `untimed` in waypoint/domain/trips.py
        } else {
            address = nil
            timeUnknown = false
        }
    }

    var isCancelled: Bool { status == "cancelled" }

    /// The pickup airport's code of a car, as the saved copy holds it in `origin`: three letters.
    var airportCode: String? {
        let code = origin?.trimmingCharacters(in: .whitespaces).uppercased() ?? ""
        return code.count == 3 && code.allSatisfy { $0.isASCII && $0.isLetter } ? code : nil
    }

    /// No time to count from: the flag, or a booking that starts and ends at midnight (`dated_only` in waypoint/domain/trips.py).
    var hasNoTime: Bool {
        func midnight(_ text: String) -> Bool {
            guard let wall = WallClock(text) else { return false }
            return wall.hour == 0 && wall.minute == 0
        }
        return timeUnknown || (midnight(startLocal) && midnight(endLocal))
    }
}
