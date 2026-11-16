import Capacitor
import SwiftUI
import WebKit

final class ShellViewController: CAPBridgeViewController {
    static var serverURL: URL?
    static var gate = OfflineGate.shared

    private static let probeInterval: TimeInterval = 5

    private var navigation: OfflineNavigation?
    private var showingCachedPage = false
    private var probing = false
    private var lastProbe = Date.distantPast

    override func instanceDescriptor() -> InstanceDescriptor {
        let descriptor = super.instanceDescriptor()
        if let url = Self.serverURL {
            descriptor.serverURL = url.absoluteString
            if let host = url.host {
                descriptor.allowedNavigationHostnames = [host, OfflinePageAddress.host]
            }
        }
        return descriptor
    }

    override func webView(with frame: CGRect, configuration: WKWebViewConfiguration) -> WKWebView {
        configuration.userContentController.add(UnauthorizedHandler(), name: UnauthorizedReport.handlerName)
        configuration.userContentController.addUserScript(
            WKUserScript(source: UnauthorizedReport.script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        if let server = Self.serverURL {
            configuration.setURLSchemeHandler(
                OfflinePageHandler(server: server, gate: Self.gate, onServerRequest: { [weak self] in self?.probeServer() }),
                forURLScheme: OfflinePageAddress.scheme)
            configuration.userContentController.addScriptMessageHandler(
                OfflineBridgeHandler(server: server, onSavingOn: { [weak self] webView in self?.refreshPages(from: webView, syncTrips: true) }),
                contentWorld: .page, name: OfflineBridgeHandler.name)
        }
        return super.webView(with: frame, configuration: configuration)
    }

    override func capacitorDidLoad() {
        guard let webView, let server = Self.serverURL else { return }
        let navigation = OfflineNavigation(
            wrapping: webView.navigationDelegate, server: server, gate: Self.gate,
            showCachedPage: { [weak self] webView in
                self?.showingCachedPage = true
                webView.load(URLRequest(url: OfflinePageAddress.home))
            },
            serverPageLoaded: { [weak self] webView in
                self?.showingCachedPage = false
                self?.refreshPages(from: webView, syncTrips: false)
            })
        self.navigation = navigation
        webView.navigationDelegate = navigation
    }

    private func refreshPages(from webView: WKWebView, syncTrips: Bool) {
        guard let server = Self.serverURL else { return }
        Task {
            if syncTrips { await OfflineSync.shared.sync() }
            let paths = await LoadedAssets.paths(in: webView, server: server)
            await OfflineSync.shared.refreshPages(loaded: paths)
        }
    }

    private func probeServer() {
        guard showingCachedPage, !probing, let server = Self.serverURL,
              Date().timeIntervalSince(lastProbe) >= Self.probeInterval else { return }
        probing = true
        lastProbe = Date()
        Task { [weak self] in
            let reachable = await ServerReachability.check(server)
            guard let self else { return }
            self.probing = false
            if reachable, self.showingCachedPage { self.webView?.load(URLRequest(url: server)) }
        }
    }
}

struct Shell: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> ShellViewController { ShellViewController() }
    func updateUIViewController(_ controller: ShellViewController, context: Context) {}
}
