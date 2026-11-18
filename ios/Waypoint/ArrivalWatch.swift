import CoreLocation
import Foundation
import UIKit
import UserNotifications

enum ArrivalAuthorization: Equatable {
    case notDetermined
    case denied
    case whenInUse
    case always
}

enum ArrivalLocationEvent: Equatable {
    case entered(String)
    case authorizationChanged
}

/// What `ArrivalWatch` needs of the system's location manager. Only region monitoring and the two authorization requests: the app never
/// asks for a location fix here, and nothing keeps one.
protocol ArrivalLocationManaging: LocationPermission, AnyObject {
    var authorization: ArrivalAuthorization { get }
    var hasPreciseLocation: Bool { get }
    var monitoredIds: [String] { get }
    func requestWhenInUse()
    func requestAlways()
    func monitor(id: String, latitude: Double, longitude: Double, radius: Double)
    func stopMonitoring(id: String)
}

final class LiveArrivalLocations: NSObject, ArrivalLocationManaging, CLLocationManagerDelegate, @unchecked Sendable {
    private let manager = CLLocationManager()
    private let lock = NSLock()
    private var pendingStarts: Set<String> = []
    private var pendingStops: Set<String> = []
    var onEvent: (@Sendable (ArrivalLocationEvent) -> Void)?

    override init() {
        super.init()
        manager.delegate = self
    }

    var authorization: ArrivalAuthorization {
        switch manager.authorizationStatus {
        case .authorizedAlways: return .always
        case .authorizedWhenInUse: return .whenInUse
        case .notDetermined: return .notDetermined
        default: return .denied
        }
    }

    var isAllowed: Bool {
        let current = authorization
        return current == .whenInUse || current == .always
    }

    var hasPreciseLocation: Bool { manager.accuracyAuthorization == .fullAccuracy }

    /// What the system holds, plus starts and minus stops that were asked for and have not run on the main queue yet, so a read right after a
    /// call sees the call.
    var monitoredIds: [String] {
        let held = Set(manager.monitoredRegions.map(\.identifier))
        lock.lock()
        defer { lock.unlock() }
        return held.union(pendingStarts).subtracting(pendingStops).sorted()
    }

    func requestWhenInUse() {
        DispatchQueue.main.async { [manager] in manager.requestWhenInUseAuthorization() }
    }

    func requestAlways() {
        DispatchQueue.main.async { [manager] in manager.requestAlwaysAuthorization() }
    }

    func monitor(id: String, latitude: Double, longitude: Double, radius: Double) {
        let region = CLCircularRegion(center: CLLocationCoordinate2D(latitude: latitude, longitude: longitude), radius: radius, identifier: id)
        region.notifyOnEntry = true
        region.notifyOnExit = false
        lock.lock()
        pendingStarts.insert(id)
        pendingStops.remove(id)
        lock.unlock()
        DispatchQueue.main.async { [self, manager] in
            manager.startMonitoring(for: region)
            lock.lock()
            pendingStarts.remove(id)
            lock.unlock()
        }
    }

    func stopMonitoring(id: String) {
        lock.lock()
        pendingStops.insert(id)
        pendingStarts.remove(id)
        lock.unlock()
        DispatchQueue.main.async { [self, manager] in
            for region in manager.monitoredRegions where region.identifier == id {
                manager.stopMonitoring(for: region)
            }
            lock.lock()
            pendingStops.remove(id)
            lock.unlock()
        }
    }

    func locationManager(_ manager: CLLocationManager, didEnterRegion region: CLRegion) {
        onEvent?(.entered(region.identifier))
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        onEvent?(.authorizationChanged)
    }
}

/// An arrival notification's content: by kind only, never a place, a name or a code (design frames A1a and A1b).
struct ArrivalNotice: Equatable {
    let id: String
    let segmentId: Int
    let tripId: Int
    let title: String
    let body: String

    init(_ place: ArrivalPlace) {
        id = ArrivalWatch.regionId(place.segmentId)
        segmentId = place.segmentId
        tripId = place.tripId
        switch place.kind {
        case .parking:
            title = "Your parking code is ready"
            body = "You’re near your parking booking. Tap to show the QR code."
        case .rentalPickup:
            title = "Your rental pickup is near"
            body = "Tap to show your confirmation number."
        case .hotel:
            title = "You’re near your hotel"
            body = "Tap to show your check-in details."
        }
    }

    /// Alerts only: no sound, no badge, passive. The user info holds the two ids and nothing else.
    func content() -> UNMutableNotificationContent {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = nil
        content.interruptionLevel = .passive
        content.userInfo = ["segmentId": segmentId, "tripId": tripId]
        return content
    }
}

protocol ArrivalNotifying: Sendable {
    func allowsAlerts() async -> Bool
    func requestAlerts() async
    func post(_ notice: ArrivalNotice) async
    func arrivalIds() async -> [String]
    func remove(ids: [String]) async
}

struct LiveArrivalNotifications: ArrivalNotifying {
    func allowsAlerts() async -> Bool {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        let status = settings.authorizationStatus
        return (status == .authorized || status == .provisional) && settings.alertSetting == .enabled
    }

    func requestAlerts() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert])
    }

    func post(_ notice: ArrivalNotice) async {
        let request = UNNotificationRequest(identifier: notice.id, content: notice.content(), trigger: nil)
        try? await UNUserNotificationCenter.current().add(request)
    }

    func arrivalIds() async -> [String] {
        let center = UNUserNotificationCenter.current()
        let pending = await center.pendingNotificationRequests().map(\.identifier)
        let delivered = await center.deliveredNotifications().map { $0.request.identifier }
        return Array(Set(pending + delivered)).filter { $0.hasPrefix(ArrivalWatch.regionPrefix) }.sorted()
    }

    func remove(ids: [String]) async {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids)
    }
}

/// Which of iOS's asks have been made, per phone: kept across sign-outs and purges, because iOS itself never asks again after an answer.
struct ArrivalAsks: @unchecked Sendable {
    enum Step: String {
        case whenInUse = "arrivalAskedLocation"
        case always = "arrivalAskedAlways"
        case notifications = "arrivalAskedNotifications"
    }

    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func done(_ step: Step) -> Bool { defaults.bool(forKey: step.rawValue) }

    func mark(_ step: Step) {
        defaults.set(true, forKey: step.rawValue)
    }
}

/// A watched booking in the arrival file, with when it last brought up a notification. The file holds no name, address or code.
struct ArrivalWatched: Codable, Equatable {
    let place: ArrivalPlace
    var notifiedAt: Date?
}

struct ArrivalFileContent: Codable, Equatable {
    let version: Int
    var watched: [ArrivalWatched]
}

/// The frequency rules of design point 5, decided from a watched entry and the time alone.
enum ArrivalRules {
    static let parkingRepeat: TimeInterval = 4 * 3600

    /// A rental pickup or hotel that has notified is done: it keeps its history and its delivered notification until the window ends, but no
    /// longer holds a region.
    static func finished(_ watched: ArrivalWatched) -> Bool {
        watched.notifiedAt != nil && watched.place.kind != .parking
    }

    static func shouldNotify(_ watched: ArrivalWatched, at now: Date) -> Bool {
        let place = watched.place
        guard now >= place.opens, now < place.closes else { return false }
        guard let last = watched.notifiedAt else { return true }
        switch place.kind {
        case .parking: return now.timeIntervalSince(last) >= parkingRepeat
        case .rentalPickup, .hotel: return false
        }
    }
}

protocol ArrivalWatching: Sendable {
    func saved(server: URL) async
    func cleared() async
}

/// Region monitoring for the places `ArrivalPlaces` found, the permission asks that make it possible and the arrival notification (design
/// `docs/design/arrival-codes/`, points 2 to 6). There is no switch: iOS's own permissions are the opt-in.
///
/// The phone's location never leaves the phone and is never kept: the only inputs are iOS's region-entry events and the authorization
/// status, and the only outputs are regions, a local notification and the arrival file (ids, kind, window, centre and radius). Nothing here
/// makes a request or logs; `tests/test_ios_arrival_privacy.py` holds that. A wake-up reads the arrival file only, never the saved trips,
/// which iOS keeps unreadable while the phone is locked.
actor ArrivalWatch: ArrivalWatching {
    static let regionPrefix = "arrival-"
    static let maxRegions = 15
    static let fileVersion = 1

    static func regionId(_ segmentId: Int) -> String { "\(regionPrefix)\(segmentId)" }

    static let shared: ArrivalWatch = {
        let live = LiveArrivalLocations()
        let watch = ArrivalWatch(
            places: ArrivalPlaces(permission: live),
            locations: live,
            notifications: LiveArrivalNotifications(),
            server: { await ServerSession.shared.server },
            protectedDataAvailable: { await MainActor.run { UIApplication.shared.isProtectedDataAvailable } })
        live.onEvent = { event in
            Task { await watch.handle(event) }
        }
        return watch
    }()

    /// Makes the manager exist from the first moment of a launch, so a region wake-up has a delegate to reach.
    static func listen() {
        _ = shared
    }

    private enum Chain {
        case idle
        case awaitingLocation
        case awaitingAlways
    }

    private let store: OfflineStore
    private let places: ArrivalPlaces
    private let locations: ArrivalLocationManaging
    private let notifications: ArrivalNotifying
    private let asks: ArrivalAsks
    private let settings: OfflineSettings
    private let currentServer: @Sendable () async -> URL?
    private let protectedDataAvailable: @Sendable () async -> Bool
    private let now: @Sendable () -> Date
    private var foreground = false
    private var chain: Chain = .idle
    private var epoch = 0
    private var refreshing = false
    private var refreshQueued = false

    init(store: OfflineStore = .shared,
         places: ArrivalPlaces,
         locations: ArrivalLocationManaging,
         notifications: ArrivalNotifying,
         asks: ArrivalAsks = ArrivalAsks(),
         settings: OfflineSettings = OfflineSettings(),
         server: @escaping @Sendable () async -> URL?,
         protectedDataAvailable: @escaping @Sendable () async -> Bool = { true },
         now: @escaping @Sendable () -> Date = { Date() }) {
        self.store = store
        self.places = places
        self.locations = locations
        self.notifications = notifications
        self.asks = asks
        self.settings = settings
        self.currentServer = server
        self.protectedDataAvailable = protectedDataAvailable
        self.now = now
    }

    // MARK: When the app is used

    func foregrounded() {
        foreground = true
    }

    /// The app became active: asks that were waiting can be made, and the places and regions are rebuilt from the saved copy (which also
    /// resumes watching after location was turned back on in iOS Settings, with no new ask).
    func activated() async {
        foreground = true
        guard let server = await currentServer() else {
            await cleared()
            return
        }
        await askIfNeeded(server: server)
        await refresh(server: server)
    }

    func backgrounded() {
        foreground = false
        chain = .idle
    }

    /// After a save of the trips: the asks, if a booking qualifies, then the places and the regions.
    func saved(server: URL) async {
        await askIfNeeded(server: server)
        await refresh(server: server)
    }

    /// Everything stopped and removed: a purge (sign-out, 401 or 403, saving off, server change, no server). The files are the store's to
    /// delete; this stops the regions and takes back every arrival notification.
    func cleared() async {
        epoch += 1
        stopRegions()
        await removeNotifications { _ in true }
    }

    func handle(_ event: ArrivalLocationEvent) async {
        switch event {
        case .entered(let id): await entered(id)
        case .authorizationChanged: await authorizationChanged()
        }
    }

    // MARK: The asks (design frames C1a to C1c)

    private func askIfNeeded(server: URL) async {
        guard canAskLocation() else { return }
        guard await places.qualifies(server: server), canAskLocation() else { return }
        asks.mark(.whenInUse)
        chain = .awaitingLocation
        locations.requestWhenInUse()
    }

    private func canAskLocation() -> Bool {
        foreground && settings.isOn && !asks.done(.whenInUse) && locations.authorization == .notDetermined
    }

    /// The Always upgrade follows an allowed While Using straight away, and notifications follow Always: each is made only as the answer to the
    /// one before it, in this launch, so turning location back on in iOS Settings later never asks again.
    private func continueAsks() async {
        let status = locations.authorization
        switch (chain, status) {
        case (.idle, _), (.awaitingLocation, .notDetermined), (.awaitingAlways, .whenInUse):
            return
        case (.awaitingLocation, .whenInUse):
            chain = .awaitingAlways
            asks.mark(.always)
            locations.requestAlways()
        case (_, .always):
            chain = .idle
            guard foreground, !asks.done(.notifications) else { return }
            asks.mark(.notifications)
            await notifications.requestAlerts()
        default:
            chain = .idle
        }
    }

    private func authorizationChanged() async {
        await continueAsks()
        guard let server = await currentServer() else {
            await cleared()
            return
        }
        await refresh(server: server)
    }

    // MARK: What is watched

    private func refresh(server: URL) async {
        if refreshing {
            refreshQueued = true
            return
        }
        refreshing = true
        repeat {
            refreshQueued = false
            await refreshOnce(server: server)
        } while refreshQueued
        refreshing = false
    }

    private func refreshOnce(server: URL) async {
        let started = epoch
        guard settings.isOn else {
            await withdraw(server: server)
            return
        }
        switch locations.authorization {
        case .notDetermined, .denied:
            await withdraw(server: server)
            return
        case .whenInUse, .always:
            break
        }
        guard await protectedDataAvailable() else { return }
        _ = await places.refresh(server: server)
        guard !Task.isCancelled, started == epoch else { return }
        await rebuild(server: server)
    }

    /// Location Never or Ask Next Time, or saving off: every region stopped, every arrival notification removed, the arrival file and the
    /// looked-up coordinates deleted. Never a trip or a picture.
    private func withdraw(server: URL) async {
        epoch += 1
        stopRegions()
        await removeNotifications { _ in true }
        store.deleteArrival(server: server)
        store.deletePlaces(server: server)
    }

    /// Chooses at most 15 places, soonest window first, and makes the regions, the arrival file and the delivered notifications match.
    func rebuild(server: URL) async {
        let started = epoch
        guard settings.isOn else {
            await withdraw(server: server)
            return
        }
        switch locations.authorization {
        case .notDetermined, .denied:
            await withdraw(server: server)
            return
        case .whenInUse:
            stopRegions()
            await removeNotifications { _ in true }
            return
        case .always:
            break
        }
        guard locations.hasPreciseLocation else {
            stopRegions()
            await removeNotifications { _ in true }
            return
        }
        guard await protectedDataAvailable() else {
            await trim(server: server)
            return
        }
        let found = await places.places(server: server)
        guard started == epoch else { return }
        let current = now()
        let earlier = readFile(server: server)?.watched ?? []
        let upcoming = found.filter { $0.closes > current }
            .sorted { ($0.opens, $0.tripId, $0.segmentId) < ($1.opens, $1.tripId, $1.segmentId) }
        let history = upcoming.map { place -> ArrivalWatched in
            let same = earlier.first { $0.place.segmentId == place.segmentId && $0.place.opens == place.opens && $0.place.closes == place.closes }
            return ArrivalWatched(place: place, notifiedAt: same?.notifiedAt)
        }
        let chosen = history.filter { !ArrivalRules.finished($0) }.prefix(Self.maxRegions)
        let finished = history.filter(ArrivalRules.finished)
        write(ArrivalFileContent(version: Self.fileVersion, watched: Array(chosen) + finished), server: server)
        let wanted = Set(chosen.map { Self.regionId($0.place.segmentId) })
        let delivered = wanted.union(finished.map { Self.regionId($0.place.segmentId) })
        let monitored = Set(locations.monitoredIds.filter { $0.hasPrefix(Self.regionPrefix) })
        for id in monitored where !wanted.contains(id) {
            locations.stopMonitoring(id: id)
        }
        for watched in chosen {
            let place = watched.place
            let id = Self.regionId(place.segmentId)
            let before = earlier.first { $0.place.segmentId == place.segmentId }?.place
            let unchanged = before.map { $0.latitude == place.latitude && $0.longitude == place.longitude && $0.radius == place.radius } ?? false
            if !monitored.contains(id) || !unchanged {
                locations.monitor(id: id, latitude: place.latitude, longitude: place.longitude, radius: place.radius)
            }
        }
        await removeNotifications { !delivered.contains($0) }
    }

    /// With the saved trips unreadable (the phone is locked), only what the arrival file says: places whose window has ended are dropped, their
    /// regions stopped and their notifications removed.
    private func trim(server: URL) async {
        guard var file = readFile(server: server) else { return }
        let current = now()
        let kept = file.watched.filter { $0.place.closes > current }
        let wanted = Set(kept.filter { !ArrivalRules.finished($0) }.map { Self.regionId($0.place.segmentId) })
        let delivered = Set(kept.map { Self.regionId($0.place.segmentId) })
        for id in locations.monitoredIds where id.hasPrefix(Self.regionPrefix) && !wanted.contains(id) {
            locations.stopMonitoring(id: id)
        }
        if kept.count != file.watched.count {
            file.watched = kept
            write(file, server: server)
        }
        await removeNotifications { !delivered.contains($0) }
    }

    // MARK: A region event

    private func entered(_ regionId: String) async {
        guard regionId.hasPrefix(Self.regionPrefix), let segmentId = Int(regionId.dropFirst(Self.regionPrefix.count)) else { return }
        guard settings.isOn, locations.authorization == .always, locations.hasPreciseLocation,
              let server = await currentServer() else { return }
        let started = epoch
        if let file = readFile(server: server),
           let index = file.watched.firstIndex(where: { $0.place.segmentId == segmentId }),
           ArrivalRules.shouldNotify(file.watched[index], at: now()),
           await notifications.allowsAlerts() {
            let entry = file.watched[index]
            guard started == epoch, settings.isOn, locations.authorization == .always, locations.hasPreciseLocation,
                  var current = readFile(server: server),
                  let position = current.watched.firstIndex(where: { $0.place == entry.place }),
                  ArrivalRules.shouldNotify(current.watched[position], at: now()) else { return }
            current.watched[position].notifiedAt = now()
            write(current, server: server)
            await notifications.post(ArrivalNotice(entry.place))
            if started != epoch { await notifications.remove(ids: [Self.regionId(segmentId)]) }
        }
        if await protectedDataAvailable() {
            await rebuild(server: server)
        } else {
            await trim(server: server)
        }
    }

    // MARK: Regions, notifications and the file

    private func stopRegions() {
        for id in locations.monitoredIds where id.hasPrefix(Self.regionPrefix) {
            locations.stopMonitoring(id: id)
        }
    }

    private func removeNotifications(where matches: (String) -> Bool) async {
        let ids = await notifications.arrivalIds().filter(matches)
        if !ids.isEmpty { await notifications.remove(ids: ids) }
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }()

    private func write(_ content: ArrivalFileContent, server: URL) {
        guard let data = try? Self.encoder.encode(content) else { return }
        try? store.saveArrival(data, for: server)
    }

    private func readFile(server: URL) -> ArrivalFileContent? {
        guard let data = store.loadArrival(server: server) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let file = try? decoder.decode(ArrivalFileContent.self, from: data), file.version == Self.fileVersion else { return nil }
        return file
    }
}
