import SwiftUI

struct SignedOutView: View {
    var signIn: () -> Void

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("You are signed out of Waypoint.")
                } footer: {
                    Text("Sign in again to see your trips.")
                }
                Section {
                    Button("Sign in") { signIn() }
                }
            }
            .navigationTitle("Waypoint")
        }
    }
}
