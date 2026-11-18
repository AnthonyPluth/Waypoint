import XCTest
@testable import Waypoint

final class FakeArrivalLocations: ArrivalLocationManaging, @unchecked Sendable {
    var authorization: ArrivalAuthorization
    var hasPreciseLocation = true
    private(set) var regions: [String: PlacePoint] = [:]
    private(set) var radii: [String: Double] = [:]
    private(set) var requests: [String] = []
    private(set) var starts: [String] = []

    init(_ authorization: ArrivalAuthorization = .notDetermined) {
        self.authorization = authorization
    }

    var isAllowed: Bool { authorization == .whenInUse || authorization == .always }
    var monitoredIds: [String] { regions.keys.sorted() }

    func requestWhenInUse() {
        requests.append("whenInUse")
    }

    func requestAlways() {
        requests.append("always")
    }

    func monitor(id: String, latitude: Double, longitude: Double, radius: Double) {
        regions[id] = PlacePoint(latitude: latitude, longitude: longitude)
        radii[id] = radius
        starts.append(id)
    }

    func stopMonitoring(id: String) {
        regions[id] = nil
        radii[id] = nil
    }
}

final class FakeArrivalNotifications: ArrivalNotifying, @unchecked Sendable {
    var allowed = true
    var beforeAllowsAlerts: (() async -> Void)?
    private(set) var requested = 0
    private(set) var posted: [ArrivalNotice] = []
    private(set) var current: [String] = []

    func allowsAlerts() async -> Bool {
        await beforeAllowsAlerts?()
        return allowed
    }

    func requestAlerts() async {
        requested += 1
    }

    func post(_ notice: ArrivalNotice) async {
        posted.append(notice)
        current.append(notice.id)
    }

    func arrivalIds() async -> [String] {
        current.filter { $0.hasPrefix(ArrivalWatch.regionPrefix) }
    }

    func remove(ids: [String]) async {
        current.removeAll { ids.contains($0) }
    }

    func leaveDelivered(_ id: String) {
        current.append(id)
    }
}

final class FakeArrivalGeocoder: AddressGeocoding, @unchecked Sendable {
    var answers: [String: PlacePoint] = [:]
    private(set) var asked: [String] = []

    func point(for address: String) async -> PlacePoint? {
        asked.append(address)
        return answers[address]
    }
}

final class ArrivalClock: @unchecked Sendable {
    var date: Date

    init(_ date: Date) {
        self.date = date
    }
}

final class ArrivalFlag: @unchecked Sendable {
    var value: Bool

    init(_ value: Bool) {
        self.value = value
    }
}

final class ArrivalFakeSaves: OfflineFetching, @unchecked Sendable {
    var data = Data()
    var status = 200

    func fetch(server: URL, bearer: String?) async throws -> (data: Data, status: Int) {
        (data, status)
    }
}

final class ArrivalRecordingWatch: ArrivalWatching, @unchecked Sendable {
    private(set) var saves: [URL] = []
    private(set) var clears = 0

    func saved(server: URL) async {
        saves.append(server)
    }

    func cleared() async {
        clears += 1
    }
}

enum ArrivalFixtures {
    static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    static func moment(_ year: Int, _ month: Int, _ day: Int, _ hour: Int, _ minute: Int = 0, zone: String = "America/Denver") -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: zone)!
        return calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute))!
    }

    static let lot = PlacePoint(latitude: 39.7392, longitude: -104.9903)
    static let inn = PlacePoint(latitude: 39.75, longitude: -105.0)
    static let counter = PlacePoint(latitude: 39.8, longitude: -104.8)

    static func segment(_ id: Int, _ kind: String, start: String, end: String, address: String?, status: String = "confirmed") -> [String: Any] {
        var details: [String: Any] = ["seat": "12A", "phone": "555-0100"]
        if let address { details["address"] = address }
        return ["id": id, "kind": kind, "status": status, "start_local": start, "start_zone": "America/Denver",
                "end_local": end, "end_zone": "America/Denver", "confirmation": "ABC123", "details": details]
    }

    static func parking(_ id: Int = 1, address: String? = "1 Main St") -> [String: Any] {
        segment(id, "parking", start: "2026-12-01T09:00", end: "2026-12-05T18:00", address: address)
    }

    static func rental(_ id: Int = 2, address: String? = "2 Rental Rd") -> [String: Any] {
        segment(id, "car", start: "2026-12-01T10:00", end: "2026-12-05T10:00", address: address)
    }

    static func hotel(_ id: Int = 3, address: String? = "3 Inn Ave") -> [String: Any] {
        segment(id, "hotel", start: "2026-12-01T15:00", end: "2026-12-05T11:00", address: address)
    }

    static func tripsJSON(_ segments: [[String: Any]]) -> Data {
        let entry: [String: Any] = ["trip": ["id": 7, "name": "Denver", "start_date": "2026-12-01", "end_date": "2026-12-08",
                                             "segments": segments] as [String: Any],
                                    "messages": [] as [Any], "codes": [] as [Any]]
        return try! JSONSerialization.data(withJSONObject: ["version": 1, "trips": [entry]])
    }
}

/// One phone: a store, a clock, the fake location manager and notification centre, and a watch over them.
final class ArrivalRig {
    let root: URL
    let suite: String
    let defaults: UserDefaults
    let store: OfflineStore
    let clock: ArrivalClock
    let protectedData: ArrivalFlag
    let locations: FakeArrivalLocations
    let notifications: FakeArrivalNotifications
    let geocoder: FakeArrivalGeocoder
    let home: URL
    let places: ArrivalPlaces
    let watch: ArrivalWatch

    init(authorization: ArrivalAuthorization = .always, at start: Date = ArrivalFixtures.moment(2026, 11, 30, 12)) {
        let rootFolder = FileManager.default.temporaryDirectory.appendingPathComponent("arrival-watch-\(UUID().uuidString)", isDirectory: true)
        let suiteName = "arrival-watch-\(UUID().uuidString)"
        let suiteDefaults = UserDefaults(suiteName: suiteName)!
        let storeNow = ArrivalFixtures.moment(2026, 11, 10, 12)
        let offlineStore = OfflineStore(root: rootFolder, calendar: ArrivalFixtures.utc, now: { storeNow })
        let time = ArrivalClock(start)
        let flag = ArrivalFlag(true)
        let manager = FakeArrivalLocations(authorization)
        let center = FakeArrivalNotifications()
        let lookups = FakeArrivalGeocoder()
        let server = URL(string: "https://waypoint.example.com")!
        let found = ArrivalPlaces(store: offlineStore, geocoder: lookups, permission: manager, calendar: ArrivalFixtures.utc,
                                  now: { time.date })
        root = rootFolder
        suite = suiteName
        defaults = suiteDefaults
        store = offlineStore
        clock = time
        protectedData = flag
        locations = manager
        notifications = center
        geocoder = lookups
        home = server
        places = found
        watch = ArrivalWatch(store: offlineStore, places: found, locations: manager, notifications: center,
                             asks: ArrivalAsks(defaults: suiteDefaults), settings: OfflineSettings(defaults: suiteDefaults),
                             server: { server }, protectedDataAvailable: { flag.value }, now: { time.date })
    }

    func cleanUp() {
        try? FileManager.default.removeItem(at: root)
        defaults.removePersistentDomain(forName: suite)
    }

    func save(_ segments: [[String: Any]]) {
        try! store.save(ArrivalFixtures.tripsJSON(segments), version: 1, for: home)
    }

    func makeSync(data: Data = Data(), status: Int = 200, hasServer: Bool = true) -> OfflineSync {
        let fetching = ArrivalFakeSaves()
        fetching.data = data
        fetching.status = status
        let address = home
        return OfflineSync(store: store, settings: OfflineSettings(defaults: defaults), fetching: fetching, arrival: places,
                           server: { hasServer ? address : nil }, bearer: { "wpa_token" }, watching: watch)
    }

    var arrivalText: String? {
        store.loadArrival(server: home).flatMap { String(data: $0, encoding: .utf8) }
    }

    var arrivalFile: URL {
        root.appendingPathComponent(OfflineStore.folderName(for: home), isDirectory: true).appendingPathComponent("arrival-watch.json")
    }
}
