import Capacitor
import SwiftUI

final class ShellViewController: CAPBridgeViewController {
    static var serverURL: URL?

    override func instanceDescriptor() -> InstanceDescriptor {
        let descriptor = super.instanceDescriptor()
        if let url = Self.serverURL {
            descriptor.serverURL = url.absoluteString
            if let host = url.host {
                descriptor.allowedNavigationHostnames = [host]
            }
        }
        return descriptor
    }
}

struct Shell: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> ShellViewController { ShellViewController() }
    func updateUIViewController(_ controller: ShellViewController, context: Context) {}
}
