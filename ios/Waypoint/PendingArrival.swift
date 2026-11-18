import Foundation

extension Notification.Name {
    static let openArrival = Notification.Name("WaypointOpenArrival")
}

/// The booking an arrival notification was tapped for: two ids, held in memory only (nothing is written, donated or indexed), handed to the
/// web view once through the bridge's `pendingArrival` request, and forgotten after two minutes. It never holds a place, a name, a code or a
/// coordinate.
final class PendingArrival: @unchecked Sendable {
    static let shared = PendingArrival()
    static let lifetime: TimeInterval = 120
    static let eventScript = "window.dispatchEvent(new Event('waypointarrival'))"

    struct Target: Equatable {
        let segmentId: Int
        let tripId: Int
    }

    private let lock = NSLock()
    private var held: (target: Target, at: Date)?

    func hold(segmentId: Int, tripId: Int, now: Date = Date()) {
        guard segmentId > 0, tripId > 0 else { return }
        lock.lock()
        held = (Target(segmentId: segmentId, tripId: tripId), now)
        lock.unlock()
    }

    func isWaiting(now: Date = Date()) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard let held else { return false }
        return now.timeIntervalSince(held.at) <= Self.lifetime
    }

    /// Answers once: the target is gone after this call, held or not.
    func take(now: Date = Date()) -> Target? {
        lock.lock()
        defer { lock.unlock() }
        defer { held = nil }
        guard let held, now.timeIntervalSince(held.at) <= Self.lifetime else { return nil }
        return held.target
    }

    func clear() {
        lock.lock()
        held = nil
        lock.unlock()
    }
}
