import SwiftUI

struct SignedOutView: View {
    var signIn: () -> Void

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("You are signed out of Waypoint.")
                } footer: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Sign in again to see your trips.")
                        Text("Saved trips were removed from this device.")
                    }
                }
                Section {
                    Button("Sign in") { signIn() }
                }
            }
            .navigationTitle("Waypoint")
        }
    }
}
