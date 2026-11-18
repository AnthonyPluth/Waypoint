import Foundation

/// A read model of the saved trips for the Siri and Shortcuts answers. It decodes only what an answer uses. It never decodes
/// `confirmation`, `manage_url`, `travelers`, any other `details` key (seat, room, phone, terminal, gate) or `messages`, so
/// none of them can reach a spoken answer or a card by accident.
struct SavedBooking: Decodable, Equatable {
    let id: Int
    let kind: String
    let status: String
    let startLocal: String
    let startZone: String
    let endLocal: String
    let endZone: String
    let origin: String?
    let destination: String?
    let provider: String?
    let flightNumber: String?
    let address: String?
    let timeUnknown: Bool

    init(id: Int, kind: String, status: String = "confirmed", startLocal: String, startZone: String, endLocal: String, endZone: String,
         origin: String? = nil, destination: String? = nil, provider: String? = nil, flightNumber: String? = nil,
         address: String? = nil, timeUnknown: Bool = false) {
        self.id = id
        self.kind = kind
        self.status = status
        self.startLocal = startLocal
        self.startZone = startZone
        self.endLocal = endLocal
        self.endZone = endZone
        self.origin = origin
        self.destination = destination
        self.provider = provider
        self.flightNumber = flightNumber
        self.address = address
        self.timeUnknown = timeUnknown
    }

    private enum Keys: String, CodingKey {
        case id, kind, status, origin, destination, provider, details
        case startLocal = "start_local"
        case startZone = "start_zone"
        case endLocal = "end_local"
        case endZone = "end_zone"
    }

    private enum DetailKeys: String, CodingKey {
        case flightNumber = "flight_number"
        case address
        case timeUnknown = "time_unknown"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: Keys.self)
        id = try values.decode(Int.self, forKey: .id)
        kind = try values.decode(String.self, forKey: .kind)
        status = try values.decodeIfPresent(String.self, forKey: .status) ?? "confirmed"
        startLocal = try values.decode(String.self, forKey: .startLocal)
        startZone = try values.decode(String.self, forKey: .startZone)
        endLocal = try values.decode(String.self, forKey: .endLocal)
        endZone = try values.decode(String.self, forKey: .endZone)
        origin = try values.decodeIfPresent(String.self, forKey: .origin)
        destination = try values.decodeIfPresent(String.self, forKey: .destination)
        provider = try values.decodeIfPresent(String.self, forKey: .provider)
        if values.contains(.details), let details = try? values.nestedContainer(keyedBy: DetailKeys.self, forKey: .details) {
            flightNumber = try? details.decodeIfPresent(String.self, forKey: .flightNumber)
            address = try? details.decodeIfPresent(String.self, forKey: .address)
            let flag: String? = try? details.decodeIfPresent(String.self, forKey: .timeUnknown)
            timeUnknown = !(flag ?? "").isEmpty
        } else {
            flightNumber = nil
            address = nil
            timeUnknown = false
        }
    }

    var isCancelled: Bool { status == "cancelled" }
}

struct SavedTrip: Decodable, Equatable {
    let id: Int
    let name: String
    let startDate: String?
    let endDate: String?
    let destination: String?
    let cities: [String: String]
    let bookings: [SavedBooking]

    init(id: Int, name: String, startDate: String? = nil, endDate: String? = nil, destination: String? = nil,
         cities: [String: String] = [:], bookings: [SavedBooking] = []) {
        self.id = id
        self.name = name
        self.startDate = startDate
        self.endDate = endDate
        self.destination = destination
        self.cities = cities
        self.bookings = bookings
    }

    private enum Keys: String, CodingKey {
        case trip, cities
    }

    private enum TripKeys: String, CodingKey {
        case id, name, destination, segments
        case startDate = "start_date"
        case endDate = "end_date"
    }

    /// One saved trip is `{ "trip": {...}, "messages": [...], "cities": {...} }`: the cities sit beside the trip, not in it.
    init(from decoder: Decoder) throws {
        let entry = try decoder.container(keyedBy: Keys.self)
        let trip = try entry.nestedContainer(keyedBy: TripKeys.self, forKey: .trip)
        id = try trip.decode(Int.self, forKey: .id)
        name = try trip.decode(String.self, forKey: .name)
        startDate = try trip.decodeIfPresent(String.self, forKey: .startDate)
        endDate = try trip.decodeIfPresent(String.self, forKey: .endDate)
        destination = try trip.decodeIfPresent(String.self, forKey: .destination)
        let segments: [Lossy<SavedBooking>]? = try? trip.decodeIfPresent([Lossy<SavedBooking>].self, forKey: .segments)
        bookings = (segments ?? []).compactMap(\.value)
        let cityMap: [String: String]? = try? entry.decodeIfPresent([String: String].self, forKey: .cities)
        cities = cityMap ?? [:]
    }
}

/// A booking that can't be read is skipped; it doesn't make the whole copy unreadable.
private struct Lossy<Value: Decodable>: Decodable {
    let value: Value?

    init(from decoder: Decoder) throws {
        value = try? Value(from: decoder)
    }
}

struct SavedCopy: Equatable {
    let savedAt: Date
    let trips: [SavedTrip]
}

enum SavedTripsReading: Equatable {
    case copy(SavedCopy)
    case nothingSaved
    case unreadable
}

enum SavedTripsReader {
    private struct Root: Decodable {
        let trips: [Lossy<SavedTrip>]
    }

    /// Reads through `SavedTrips.read`, as the bridge does, and decodes only the read model.
    static func read(_ store: OfflineStore, server: URL) -> SavedTripsReading {
        guard let copy = SavedTrips.read(store, server: server) else {
            guard let snapshot = store.load(server: server) else { return .nothingSaved }
            return snapshot.version == OfflineSync.supportedVersion ? .nothingSaved : .unreadable
        }
        guard let data = try? JSONSerialization.data(withJSONObject: ["trips": copy.trips]),
              let root = try? JSONDecoder().decode(Root.self, from: data) else { return .unreadable }
        let trips = root.trips.compactMap(\.value)
        return trips.isEmpty ? .unreadable : .copy(SavedCopy(savedAt: copy.savedAt, trips: trips))
    }
}
