import SwiftUI

struct ConnectView: View {
    var connected: () -> Void
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
                        .disabled(working || address.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .navigationTitle("Waypoint")
        }
    }

    private func connect() {
        working = true
        failure = nil
        Task { @MainActor in
            defer { working = false }
            do {
                try await ServerSession.shared.connect(to: address) { SignIn() }
                connected()
            } catch {
                failure = error.localizedDescription
            }
        }
    }
}
