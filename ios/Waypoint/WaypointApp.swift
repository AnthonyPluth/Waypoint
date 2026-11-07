import SwiftUI

@main
struct WaypointApp: App {
    @State private var phase: Phase = .starting
    @Environment(\.scenePhase) private var scenePhase

    enum Phase: Equatable {
        case starting
        case connect
        case shell
        case failed(String)
    }

    var body: some Scene {
        WindowGroup {
            Group {
                content
            }
            .onChange(of: scenePhase) { newPhase in
                if newPhase == .active { Task { await renewWebSession() } }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .starting:
            ProgressView().task { await open() }
        case .connect:
            ConnectView { await open() }
        case .shell:
            Shell().ignoresSafeArea()
        case .failed(let why):
            VStack(spacing: 16) {
                Text(why).multilineTextAlignment(.center)
                Button("Try again") { phase = .starting }
                Button("Use another Waypoint", role: .destructive) {
                    Task {
                        await ServerSession.shared.signOut()
                        phase = .connect
                    }
                }
            }
            .padding()
        }
    }

    @MainActor
    private func open() async {
        Task { await ServerSession.shared.retryPendingRevocations() }
        guard await ServerSession.shared.isConnected else {
            phase = .connect
            return
        }
        do {
            ShellViewController.serverURL = try await ServerSession.shared.prepareWebView()
            phase = .shell
        } catch ServerError.signedOut {
            await ServerSession.shared.signOut()
            phase = .connect
        } catch {
            phase = .failed(error.localizedDescription)
        }
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
