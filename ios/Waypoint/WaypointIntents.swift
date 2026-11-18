import AppIntents
import SwiftUI
import UIKit

/// Reads what an intent needs and returns its `Answer`. It reads only the saved trips of the server in `ServerSession`, the same
/// folder the bridge reads, and makes no network request: it has no `ServerClient` and no `URLSession`.
struct TripAnswerService {
    enum Question: Equatable {
        case nextFlight, tonight, checkOut, parking
    }

    var currentServer: @Sendable () async -> URL?
    var protectedDataAvailable: @Sendable () async -> Bool
    var store: OfflineStore
    var settings: OfflineSettings
    var now: @Sendable () -> Date
    var calendar: Calendar

    static let live = TripAnswerService(
        currentServer: { await ServerSession.shared.server },
        protectedDataAvailable: { await MainActor.run { UIApplication.shared.isProtectedDataAvailable } },
        store: .shared,
        settings: OfflineSettings(),
        now: { Date() },
        calendar: .current)

    func answer(_ question: Question) async -> Answer {
        // The saved trips are `.complete` file protected: with the phone locked they can't be read, so don't try.
        guard await protectedDataAvailable() else { return .locked }
        guard let server = await currentServer() else { return .notSignedIn }
        guard settings.isOn else { return .savingOff }
        switch SavedTripsReader.read(store, server: server) {
        case .nothingSaved:
            return .nothingSaved
        case .unreadable:
            return .unreadable
        case .copy(let copy):
            let answers = TripAnswers(now: now(), calendar: calendar)
            switch question {
            case .nextFlight: return answers.nextFlight(copy)
            case .tonight: return answers.tonight(copy)
            case .checkOut: return answers.checkOut(copy)
            case .parking: return answers.parking(copy)
            }
        }
    }
}

/// What the intents use. Tests replace these; the app never does.
enum IntentRuntime {
    static var service = TripAnswerService.live
    static var pages = PendingPage.shared
}

struct NextFlightIntent: AppIntent {
    static var title: LocalizedStringResource = "Next flight"
    static var description = IntentDescription("Says when your next flight leaves, from the trips saved on this iPhone.")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    init() {}

    func perform() async throws -> some IntentResult & ProvidesDialog & ShowsSnippetView {
        let answer = await IntentRuntime.service.answer(.nextFlight)
        IntentRuntime.pages.hold(answer.page)
        return .result(dialog: "\(answer.spoken)", view: TripAnswerCard(answer: answer))
    }
}

struct TonightStayIntent: AppIntent {
    static var title: LocalizedStringResource = "Tonight's stay"
    static var description = IntentDescription("Says where you are staying tonight, from the trips saved on this iPhone.")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    init() {}

    func perform() async throws -> some IntentResult & ProvidesDialog & ShowsSnippetView {
        let answer = await IntentRuntime.service.answer(.tonight)
        IntentRuntime.pages.hold(answer.page)
        return .result(dialog: "\(answer.spoken)", view: TripAnswerCard(answer: answer))
    }
}

struct CheckOutIntent: AppIntent {
    static var title: LocalizedStringResource = "Check-out"
    static var description = IntentDescription("Says when you check out, from the trips saved on this iPhone.")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    init() {}

    func perform() async throws -> some IntentResult & ProvidesDialog & ShowsSnippetView {
        let answer = await IntentRuntime.service.answer(.checkOut)
        IntentRuntime.pages.hold(answer.page)
        return .result(dialog: "\(answer.spoken)", view: TripAnswerCard(answer: answer))
    }
}

/// Opens the app at the trip of the current or next parking booking and says only the lot. The parking code is never spoken, shown
/// or saved here: the web app's booking shows it from the server once the app is open.
struct OpenParkingIntent: AppIntent {
    static var title: LocalizedStringResource = "Parking code"
    static var description = IntentDescription("Opens your parking booking in Waypoint, where its QR code is.")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication
    static var openAppWhenRun: Bool = true

    init() {}

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let answer = await IntentRuntime.service.answer(.parking)
        IntentRuntime.pages.hold(answer.page)
        return .result(dialog: "\(answer.spoken)")
    }
}

/// The phrases work by voice with no setup. Apple needs the app's name in every one.
struct WaypointShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: NextFlightIntent(),
            phrases: [
                "When is my next flight in \(.applicationName)",
                "\(.applicationName) next flight",
                "When do I fly in \(.applicationName)",
            ],
            shortTitle: "Next flight",
            systemImageName: "airplane")
        AppShortcut(
            intent: TonightStayIntent(),
            phrases: [
                "Where am I staying tonight in \(.applicationName)",
                "\(.applicationName) hotel",
            ],
            shortTitle: "Tonight's stay",
            systemImageName: "bed.double.fill")
        AppShortcut(
            intent: CheckOutIntent(),
            phrases: [
                "When do I check out in \(.applicationName)",
            ],
            shortTitle: "Check-out",
            systemImageName: "door.left.hand.open")
        AppShortcut(
            intent: OpenParkingIntent(),
            phrases: [
                "Show my parking code in \(.applicationName)",
                "\(.applicationName) parking",
            ],
            shortTitle: "Parking code",
            systemImageName: "parkingsign")
    }
}
