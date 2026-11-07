import SwiftUI

struct ConnectView: View {
    var connected: () async -> Void

    static func canConnect(address: String, working: Bool) -> Bool {
        !working && !address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    @State private var address = ""
    @State private var working = false
    @State private var failure: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://waypoint.example.com", text: $address)
                        .textContentType(.URL)
                        .keyboardType(.URL)
                        .autocapitalization(.none)
                        .autocorrectionDisabled()
                        .disabled(working)
                } header: {
                    Text("Your Waypoint")
                } footer: {
                    Text("The address of the Waypoint you run. The app talks only to that server.")
                }
                if let failure {
                    Section { Text(failure).foregroundStyle(.red) }
                }
                Section {
                    Button(working ? "Connecting…" : "Connect") { connect() }
                        .disabled(!Self.canConnect(address: address, working: working))
                }
            }
            .navigationTitle("Waypoint")
        }
    }

    private func connect() {
        guard Self.canConnect(address: address, working: working) else { return }
        working = true
        failure = nil
        Task { @MainActor in
            defer { working = false }
            do {
                try await ServerSession.shared.connect(to: address) { SignIn() }
                await connected()
            } catch {
                failure = error.localizedDescription
            }
        }
    }
}
