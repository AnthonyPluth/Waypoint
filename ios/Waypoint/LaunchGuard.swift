import Foundation

/// A region wake-up can relaunch the app in the background, often with the phone locked. The launch then does nothing: it contacts no server
/// and reads nothing, and starts when the app is next active with the phone unlocked.
enum LaunchGuard {
    static func mayOpen(active: Bool, protectedDataAvailable: Bool) -> Bool {
        active && protectedDataAvailable
    }
}
