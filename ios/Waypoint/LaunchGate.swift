import Foundation

/// A region wake-up can relaunch the app in the background, often with the phone locked. The launch then does nothing: it contacts no server
/// and reads nothing, and starts the first time the app is active with the phone unlocked. Once started it is never started again and never
/// cancelled by the app going inactive and back; `end()` lets a launch that failed be started again.
final class LaunchGate {
    private let lock = NSLock()
    private var running = false

    func begin(active: Bool, protectedDataAvailable: Bool) -> Bool {
        guard active, protectedDataAvailable else { return false }
        lock.lock()
        defer { lock.unlock() }
        if running { return false }
        running = true
        return true
    }

    func end() {
        lock.lock()
        running = false
        lock.unlock()
    }
}

extension LaunchGate {
    /// The scene-phase callback that runs `ArrivalWatch.activated()` on becoming active finds the shell not open yet on a cold launch (the launch
    /// is still running), and a launch that opens the cached page offline makes no save that would run it either. So a launch that has opened the
    /// shell and is still active runs it itself, once, after `begin` allowed it: never from a background relaunch or a locked phone, which
    /// `begin` refuses.
    static func activatesArrival(shellOpen: Bool, active: Bool) -> Bool {
        shellOpen && active
    }
}

enum LaunchDecision: Equatable {
    case launch
    case purgeAndConnect
    case failed(String)

    static let unreadable = "Waypoint can’t read your saved sign-in right now. Try again, or unlock your phone and reopen the app."

    /// What a launch does for what the Keychain says. Only a Keychain that was read and holds no sign-in purges the saved trips; one that
    /// cannot be read shows the failure screen, whose Try again reads it again, and deletes nothing.
    static func of(_ standing: ServerSession.Standing) -> LaunchDecision {
        switch standing {
        case .connected: return .launch
        case .notConnected: return .purgeAndConnect
        case .unknown: return .failed(unreadable)
        }
    }
}
