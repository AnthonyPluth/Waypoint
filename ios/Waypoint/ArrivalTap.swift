import Foundation
import UserNotifications

/// What a tap on an arrival notification hands over: the two ids its `userInfo` carries, and only when the notification is one of
/// `ArrivalWatch`'s (its identifier names the same booking). Nothing else of the notification is read.
enum ArrivalTap {
    static func target(identifier: String, userInfo: [AnyHashable: Any]) -> PendingArrival.Target? {
        guard identifier.hasPrefix(ArrivalWatch.regionPrefix),
              let segmentId = userInfo["segmentId"] as? Int, let tripId = userInfo["tripId"] as? Int,
              segmentId > 0, tripId > 0, identifier == ArrivalWatch.regionId(segmentId) else { return nil }
        return PendingArrival.Target(segmentId: segmentId, tripId: tripId)
    }

    /// Holds the target and tells the shell. Contacts no server and reads no file, so a tap that launches the app does nothing until the
    /// launch itself (`LaunchGate`) has run.
    @discardableResult
    static func respond(identifier: String, userInfo: [AnyHashable: Any], pending: PendingArrival = .shared,
                        center: NotificationCenter = .default) -> Bool {
        guard let target = target(identifier: identifier, userInfo: userInfo) else { return false }
        pending.hold(segmentId: target.segmentId, tripId: target.tripId)
        center.post(name: .openArrival, object: nil)
        return true
    }
}

final class ArrivalTapHandler: NSObject, UNUserNotificationCenterDelegate {
    static let shared = ArrivalTapHandler()

    static func install() {
        UNUserNotificationCenter.current().delegate = shared
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let request = response.notification.request
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier {
            ArrivalTap.respond(identifier: request.identifier, userInfo: request.content.userInfo)
        }
        completionHandler()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([])
    }
}
