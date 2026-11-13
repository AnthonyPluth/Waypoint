import Capacitor
import SwiftUI
import WebKit

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

    override func webView(with frame: CGRect, configuration: WKWebViewConfiguration) -> WKWebView {
        configuration.userContentController.add(UnauthorizedHandler(), name: UnauthorizedReport.handlerName)
        configuration.userContentController.addUserScript(
            WKUserScript(source: UnauthorizedReport.script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        return super.webView(with: frame, configuration: configuration)
    }
}

struct Shell: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> ShellViewController { ShellViewController() }
    func updateUIViewController(_ controller: ShellViewController, context: Context) {}
}
