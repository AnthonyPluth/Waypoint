import SwiftUI
import UIKit

@main
struct WaypointApp: App {
    @State private var phase: Phase = .starting
    @State private var launch = LaunchGate()
    @Environment(\.scenePhase) private var scenePhase

    enum Phase: Equatable {
        case starting
        case connect
        case signedOut
        case shell
        case failed(String)
    }

    init() {
        ArrivalWatch.listen()
        ArrivalTapHandler.install()
    }

    var body: some Scene {
        WindowGroup {
            Group {
                content
            }
            .onChange(of: scenePhase) { newPhase in
                if newPhase == .active {
                    Task { await openIfAllowed(active: true) }
                    Task {
                        await ArrivalWatch.shared.foregrounded()
                        await returnToForeground()
                    }
                } else if newPhase == .background {
                    Task {
                        await ArrivalWatch.shared.backgrounded()
                        await ArrivalHere.shared.backgrounded()
                    }
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .webViewUnauthorized)) { _ in
                Task { await endSession() }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .starting:
            ProgressView().task { await openIfAllowed(active: scenePhase == .active) }
        case .connect:
            ConnectView { await open() }
        case .signedOut:
            SignedOutView { phase = .connect }
        case .shell:
            Shell().ignoresSafeArea()
        case .failed(let why):
            VStack(spacing: 16) {
                Text(why).multilineTextAlignment(.center)
                Button("Try again") { phase = .starting }
                Button("Use another Waypoint", role: .destructive) {
                    Task {
                        await ServerSession.shared.signOut()
                        phase = .signedOut
                    }
                }
            }
            .padding()
        }
    }

    /// `active` is said by the caller, never read here from `scenePhase`: iOS 16's `onChange(of:perform:)` runs the closure made with the view
    /// before the change, so `scenePhase` read from it (or from a method it calls) is still the old `.inactive`. A cold launch's first render is
    /// not active yet either, so reading it here refused both starts and left the spinner up for good. After `open()` the app's live state says
    /// whether it is still active.
    @MainActor
    private func openIfAllowed(active: Bool) async {
        guard phase == .starting,
              launch.begin(active: active, protectedDataAvailable: UIApplication.shared.isProtectedDataAvailable) else { return }
        await open()
        launch.end()
        if LaunchGate.activatesArrival(shellOpen: phase == .shell, active: UIApplication.shared.applicationState == .active) {
            await ArrivalWatch.shared.activated()
        }
    }

    @MainActor
    private func open() async {
        Task { await ServerSession.shared.retryPendingRevocations() }
        switch LaunchDecision.of(await ServerSession.shared.standing()) {
        case .failed(let why):
            phase = .failed(why)
            return
        case .purgeAndConnect:
            await OfflineSync.shared.purge()
            phase = .connect
            return
        case .launch:
            break
        }
        switch await ServerSession.shared.launchWebView() {
        case .server(let url):
            ShellViewController.serverURL = url
            phase = .shell
            Task { await OfflineSync.shared.sync() }
        case .cachedPage(let url):
            ShellViewController.serverURL = url
            phase = .shell
        case .signedOut:
            phase = .connect
        case .failed(let why):
            phase = .failed(why)
        }
    }

    @MainActor
    private func endSession() async {
        guard phase == .shell else { return }
        phase = .signedOut
        await ServerSession.shared.signOut()
    }

    @MainActor
    private func returnToForeground() async {
        await renewWebSession()
        guard phase == .shell else { return }
        if PendingPage.shared.peek() != nil {
            NotificationCenter.default.post(name: .openSavedPage, object: nil)
        }
        await ArrivalWatch.shared.activated()
        await OfflineSync.shared.sync()
    }

    @MainActor
    private func renewWebSession() async {
        guard phase == .shell, await ServerSession.shared.webSessionNeedsRenewal() else { return }
        do {
            _ = try await ServerSession.shared.prepareWebView()
        } catch ServerError.signedOut {
            await ServerSession.shared.signOut()
            phase = .connect
        } catch {
            return
        }
    }
}
