import Foundation

extension Notification.Name {
    static let openSavedPage = Notification.Name("WaypointOpenSavedPage")
}

/// The page a Siri or Shortcuts card opens when it is tapped (`#trip/3`, `#trip/3/flight/12`). A tap on the card brings the app
/// forward; the app then opens the page it finds here, if it was put there a moment ago. It is held in memory only (nothing is
/// written, donated or indexed), used once, and only the two hash routes are accepted.
final class PendingPage: @unchecked Sendable {
    static let shared = PendingPage()
    static let lifetime: TimeInterval = 120

    private let lock = NSLock()
    private var held: (page: String, at: Date)?

    static func isValid(_ page: String) -> Bool {
        page.range(of: #"^#trip/[0-9]+(/flight/[0-9]+)?\z"#, options: .regularExpression) != nil
    }

    /// The script that opens a page in the web view, or nil for anything but the two trip routes.
    static func script(for page: String) -> String? {
        isValid(page) ? "window.location.hash = '\(page)'" : nil
    }

    func hold(_ page: String?, now: Date = Date()) {
        lock.lock()
        defer { lock.unlock() }
        if let page, Self.isValid(page) {
            held = (page, now)
        } else {
            held = nil
        }
    }

    /// The page held, without using it up: the shell clears it once it has applied it.
    func peek(now: Date = Date()) -> String? {
        lock.lock()
        defer { lock.unlock() }
        guard let held, now.timeIntervalSince(held.at) <= Self.lifetime else { return nil }
        return held.page
    }

    func clear() {
        lock.lock()
        held = nil
        lock.unlock()
    }

    func take(now: Date = Date()) -> String? {
        lock.lock()
        defer { lock.unlock() }
        defer { held = nil }
        guard let held, now.timeIntervalSince(held.at) <= Self.lifetime else { return nil }
        return held.page
    }
}
