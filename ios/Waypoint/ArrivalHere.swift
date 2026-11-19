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
    static func windowOpen(_ places: [ArrivalPlace], at now: Date) -> [ArrivalPlace] {
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
        windowOpen(places, at: now)
            .filter { metres(from: point, to: PlacePoint(latitude: $0.latitude, longitude: $0.longitude)) <= $0.radius }
            .max { ($0.opens, $0.segmentId) < ($1.opens, $1.segmentId) }
    }
}

/// A single location request through the system's manager, with a time limit. A fix less precise than `widest` metres counts as none.
/// An ask that comes while a request is outstanding joins it and gets its answer, so being busy is never an answer of none. A request
/// whose askers are all cancelled (the app went to the background) is ended at once, so the next check makes its own.
final class LiveArrivalFix: NSObject, ArrivalFixing, CLLocationManagerDelegate, @unchecked Sendable {
    static let timeout: TimeInterval = 10
    static let widest = 500.0

    /// One ask of `current()`; `cancelled` is set when its task is cancelled, even before the request has been made.
    private final class Ask: @unchecked Sendable {
        var cancelled = false
    }

    private let lock = NSLock()
    private let ask: @Sendable (CLLocationManager) -> Void
    private var manager: CLLocationManager?
    private var waiters: [(ask: Ask, continuation: CheckedContinuation<PlacePoint?, Never>)] = []

    init(ask: @escaping @Sendable (CLLocationManager) -> Void = { $0.requestLocation() }) {
        self.ask = ask
        super.init()
    }

    var isAllowed: Bool {
        let status = CLLocationManager()
        let permitted = status.authorizationStatus == .authorizedWhenInUse || status.authorizationStatus == .authorizedAlways
        return permitted && status.accuracyAuthorization == .fullAccuracy
    }

    /// Whether a request is outstanding.
    var hasOutstandingRequest: Bool {
        lock.lock()
        defer { lock.unlock() }
        return manager != nil
    }

    /// How many asks are waiting on the outstanding request.
    var waitingCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return waiters.count
    }

    func current() async -> PlacePoint? {
        let thisAsk = Ask()
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                DispatchQueue.main.async { [self] in
                    let asking = CLLocationManager()
                    lock.lock()
                    if thisAsk.cancelled {
                        lock.unlock()
                        continuation.resume(returning: nil)
                        return
                    }
                    waiters.append((thisAsk, continuation))
                    let starting = manager == nil
                    if starting { manager = asking }
                    lock.unlock()
                    guard starting else { return }
                    asking.delegate = self
                    asking.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
                    ask(asking)
                    DispatchQueue.main.asyncAfter(deadline: .now() + Self.timeout) { [self] in
                        finish(nil, asked: asking)
                    }
                }
            }
        } onCancel: {
            release(thisAsk)
        }
    }

    /// The task behind `thisAsk` was cancelled: it stops waiting, answering none, and the request ends if nobody else waits on it.
    private func release(_ thisAsk: Ask) {
        lock.lock()
        thisAsk.cancelled = true
        guard let index = waiters.firstIndex(where: { $0.ask === thisAsk }) else {
            lock.unlock()
            return
        }
        let gone = waiters.remove(at: index)
        var ended: CLLocationManager?
        if waiters.isEmpty {
            ended = manager
            manager = nil
        }
        lock.unlock()
        if let ended {
            DispatchQueue.main.async {
                ended.delegate = nil
                ended.stopUpdatingLocation()
            }
        }
        gone.continuation.resume(returning: nil)
    }

    private func finish(_ point: PlacePoint?, asked: CLLocationManager) {
        lock.lock()
        guard manager === asked else {
            lock.unlock()
            return
        }
        let held = waiters
        waiters = []
        manager = nil
        lock.unlock()
        asked.delegate = nil
        for one in held { one.continuation.resume(returning: point) }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        received(locations, from: manager)
    }

    func received(_ locations: [CLLocation], from manager: CLLocationManager) {
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
    private var check: (server: URL, task: Task<Outcome, Never>)?

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

    /// A check that could not start (saving off, no permission, nothing saved yet or no window open) is not cached, so the next ask tries
    /// again once the save, the lookup or the permission has happened; only a check that asked where the phone is stays for the session.
    private enum Outcome {
        case notReady
        case checked(ArrivalHereAnswer?)
    }

    func answer(server: URL) async -> ArrivalHereAnswer? {
        if let running = check, running.server == server {
            switch await running.task.value {
            case .notReady:
                if check?.task == running.task { check = nil }
            case .checked(let cached):
                guard let cached else { return nil }
                if await stillHolds(cached, server: server) { return cached }
                check = nil
                return nil
            }
        }
        check?.task.cancel()
        let task = Task { await look(server: server) }
        check = (server, task)
        switch await task.value {
        case .notReady:
            if check?.task == task { check = nil }
            return nil
        case .checked(let found):
            return found
        }
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

    private func look(server: URL) async -> Outcome {
        guard settings.isOn, fix.isAllowed, await protectedDataAvailable() else { return .notReady }
        let found = await places.places(server: server)
        guard !ArrivalHereRules.windowOpen(found, at: now()).isEmpty else { return .notReady }
        guard let point = await fix.current(), !Task.isCancelled else { return .checked(nil) }
        guard let place = ArrivalHereRules.place(among: found, at: point, now: now()) else { return .checked(nil) }
        return .checked(ArrivalHereAnswer(segmentId: place.segmentId, tripId: place.tripId))
    }
}
