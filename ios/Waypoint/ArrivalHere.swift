import CoreLocation
import Foundation
import UIKit

/// The one booking whose circle the phone is in right now, as two ids. Never a coordinate, a place, a name or a code.
struct ArrivalHereAnswer: Equatable {
    let segmentId: Int
    let tripId: Int
}

protocol ArrivalHereAnswering: Sendable {
    func answer(server: URL) async -> ArrivalHereAnswer?
    func backgrounded() async
}

/// One look at where the phone is. It is compared in memory with the places and dropped: nothing here stores, sends or logs it.
protocol ArrivalFixing: Sendable {
    /// While Using or Always, with Precise Location on.
    var isAllowed: Bool { get }
    func current() async -> PlacePoint?
}

enum ArrivalHereRules {
    /// The bookings whose window is open at `now`.
    static func open(_ places: [ArrivalPlace], at now: Date) -> [ArrivalPlace] {
        places.filter { $0.opens <= now && now < $0.closes }
    }

    /// Great-circle distance in metres.
    static func metres(from a: PlacePoint, to b: PlacePoint) -> Double {
        let earth = 6_371_000.0
        let lat1 = a.latitude * .pi / 180
        let lat2 = b.latitude * .pi / 180
        let dLat = (b.latitude - a.latitude) * .pi / 180
        let dLon = (b.longitude - a.longitude) * .pi / 180
        let h = sin(dLat / 2) * sin(dLat / 2) + cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * earth * asin(min(1, h.squareRoot()))
    }

    /// The booking whose window opened last among those whose circle holds the point (design A3: one card at a time).
    static func place(among places: [ArrivalPlace], at point: PlacePoint, now: Date) -> ArrivalPlace? {
        open(places, at: now)
            .filter { metres(from: point, to: PlacePoint(latitude: $0.latitude, longitude: $0.longitude)) <= $0.radius }
            .max { ($0.opens, $0.segmentId) < ($1.opens, $1.segmentId) }
    }
}

/// A single location request through the system's manager, with a time limit. A fix less precise than `widest` metres counts as none.
final class LiveArrivalFix: NSObject, ArrivalFixing, CLLocationManagerDelegate, @unchecked Sendable {
    static let timeout: TimeInterval = 10
    static let widest = 500.0

    private let lock = NSLock()
    private var manager: CLLocationManager?
    private var waiting: CheckedContinuation<PlacePoint?, Never>?

    var isAllowed: Bool {
        let status = CLLocationManager()
        let permitted = status.authorizationStatus == .authorizedWhenInUse || status.authorizationStatus == .authorizedAlways
        return permitted && status.accuracyAuthorization == .fullAccuracy
    }

    func current() async -> PlacePoint? {
        await withCheckedContinuation { continuation in
            DispatchQueue.main.async { [self] in
                let asking = CLLocationManager()
                lock.lock()
                let busy = waiting != nil
                if !busy {
                    waiting = continuation
                    manager = asking
                }
                lock.unlock()
                if busy {
                    continuation.resume(returning: nil)
                    return
                }
                asking.delegate = self
                asking.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
                asking.requestLocation()
                DispatchQueue.main.asyncAfter(deadline: .now() + Self.timeout) { [self] in
                    finish(nil, asked: asking)
                }
            }
        }
    }

    private func finish(_ point: PlacePoint?, asked: CLLocationManager) {
        lock.lock()
        guard manager === asked, let continuation = waiting else {
            lock.unlock()
            return
        }
        waiting = nil
        manager = nil
        lock.unlock()
        asked.delegate = nil
        continuation.resume(returning: point)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last, last.horizontalAccuracy >= 0, last.horizontalAccuracy <= Self.widest else {
            finish(nil, asked: manager)
            return
        }
        let point = PlacePoint(latitude: last.coordinate.latitude, longitude: last.coordinate.longitude)
        finish(point.isValid ? point : nil, asked: manager)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(nil, asked: manager)
    }
}

/// The check behind the card on Upcoming (design frame A3): once for each time the app comes to the front, one location request, compared in
/// memory with the places of the saved trips and dropped. What is kept, until the app goes to the background, is the answer: two ids. A
/// request is made only when a watched booking's window is open, and never without While Using or Always, Precise Location and saving on.
/// It asks for no permission, reads nothing while the phone is locked and contacts no server.
actor ArrivalHere: ArrivalHereAnswering {
    static let shared = ArrivalHere(
        places: ArrivalPlaces(), fix: LiveArrivalFix(),
        protectedDataAvailable: { await MainActor.run { UIApplication.shared.isProtectedDataAvailable } })

    private let places: ArrivalPlaces
    private let fix: ArrivalFixing
    private let settings: OfflineSettings
    private let protectedDataAvailable: @Sendable () async -> Bool
    private let now: @Sendable () -> Date
    private var check: (server: URL, task: Task<ArrivalHereAnswer?, Never>)?

    init(places: ArrivalPlaces,
         fix: ArrivalFixing,
         settings: OfflineSettings = OfflineSettings(),
         protectedDataAvailable: @escaping @Sendable () async -> Bool = { true },
         now: @escaping @Sendable () -> Date = { Date() }) {
        self.places = places
        self.fix = fix
        self.settings = settings
        self.protectedDataAvailable = protectedDataAvailable
        self.now = now
    }

    func answer(server: URL) async -> ArrivalHereAnswer? {
        if let running = check, running.server == server {
            let cached = await running.task.value
            guard let cached else { return nil }
            if await stillHolds(cached, server: server) { return cached }
            check = nil
            return nil
        }
        check?.task.cancel()
        let task = Task { await look(server: server) }
        check = (server, task)
        return await task.value
    }

    /// The app went to the background: the answer is forgotten, so the next time it comes forward asks again.
    func backgrounded() {
        check?.task.cancel()
        check = nil
    }

    /// A cached answer is given again only while saving is on, the phone can be asked and the booking is still among the saved places:
    /// switching saving off or any purge ends it at once, in the same foreground session.
    private func stillHolds(_ answer: ArrivalHereAnswer, server: URL) async -> Bool {
        guard settings.isOn, fix.isAllowed, await protectedDataAvailable() else { return false }
        let found = await places.places(server: server)
        return found.contains { $0.segmentId == answer.segmentId && $0.tripId == answer.tripId }
    }

    private func look(server: URL) async -> ArrivalHereAnswer? {
        guard settings.isOn, fix.isAllowed, await protectedDataAvailable() else { return nil }
        let found = await places.places(server: server)
        guard !ArrivalHereRules.open(found, at: now()).isEmpty else { return nil }
        guard let point = await fix.current(), !Task.isCancelled else { return nil }
        guard let place = ArrivalHereRules.place(among: found, at: point, now: now()) else { return nil }
        return ArrivalHereAnswer(segmentId: place.segmentId, tripId: place.tripId)
    }
}
