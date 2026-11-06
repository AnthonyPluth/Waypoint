import SwiftUI

@main
struct WaypointApp: App {
    @State private var phase: Phase = .starting

    enum Phase: Equatable {
        case starting
        case connect
        case shell
        case failed(String)
    }

    var body: some Scene {
        WindowGroup {
            switch phase {
            case .starting:
                ProgressView().task { await open() }
            case .connect:
                ConnectView { Task { await open() } }
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
    }

    @MainActor
    private func open() async {
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
}
