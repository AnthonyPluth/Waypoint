import Capacitor
import SwiftUI
import WebKit

final class ShellViewController: CAPBridgeViewController {
    static var serverURL: URL?
    static var gate = OfflineGate.shared
    static var renewSession: @Sendable () async -> Bool = { await ServerSession.shared.renewForReturn() }

    private static let probeInterval: TimeInterval = 5

    private var navigation: OfflineNavigation?
    private var showingCachedPage = false
    private var probing = false
    private var lastProbe = Date.distantPast

    override func instanceDescriptor() -> InstanceDescriptor {
        let descriptor = super.instanceDescriptor()
        if let url = Self.serverURL {
            descriptor.serverURL = url.absoluteString
            // A tap on a Siri card that launched the app: open the page it names (only `#trip/...` routes pass).
            if let page = PendingPage.shared.peek() { descriptor.serverURL = url.absoluteString + page }
            if let host = url.host {
                descriptor.allowedNavigationHostnames = [host, OfflinePageAddress.host]
            }
        }
        return descriptor
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        NotificationCenter.default.addObserver(self, selector: #selector(openSavedPage(_:)), name: .openSavedPage, object: nil)
    }

    @objc private func openSavedPage(_ note: Notification) {
        guard let webView else { return }
        applyPendingPage(to: webView)
    }

    /// Opens the page a Siri card named, on whichever page is showing (the server's or the cached one), and forgets it only once
    /// the script ran. A cold start that fell back to the cached page keeps it until that page has loaded.
    private func applyPendingPage(to webView: WKWebView) {
        guard let page = PendingPage.shared.peek(), let script = PendingPage.script(for: page) else { return }
        webView.evaluateJavaScript(script) { _, error in
            if error == nil { PendingPage.shared.clear() }
        }
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
        let webView = super.webView(with: frame, configuration: configuration)
        webView.allowsBackForwardNavigationGestures = true
        return webView
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
                self?.applyPendingPage(to: webView)
                self?.refreshPages(from: webView, syncTrips: false)
            },
            cachedPageLoaded: { [weak self] webView in
                self?.applyPendingPage(to: webView)
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
            var ready = false
            if reachable { ready = await Self.renewSession() }
            guard let self else { return }
            self.probing = false
            if ready, self.showingCachedPage {
                self.webView?.load(URLRequest(url: server))
                await OfflineSync.shared.sync()
            }
        }
    }
}

struct Shell: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> ShellViewController { ShellViewController() }
    func updateUIViewController(_ controller: ShellViewController, context: Context) {}
}
