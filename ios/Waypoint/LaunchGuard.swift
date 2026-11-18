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
