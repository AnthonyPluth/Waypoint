import Foundation
import WebKit

struct OfflineGate {
    static let shared = OfflineGate(store: .shared, pages: .shared)

    let store: OfflineStore
    let pages: OfflinePages

    func canShowCachedPage(for server: URL) -> Bool {
        guard SavedTrips.read(store, server: server) != nil else {
            pages.purge(server: server)
            return false
        }
        return pages.hasPage(for: server)
    }

    func file(_ path: String, for server: URL) -> Data? {
        canShowCachedPage(for: server) ? pages.file(path, for: server) : nil
    }
}

enum OfflineFallback {
    private static let unreachable: Set<URLError.Code> = [
        .notConnectedToInternet, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed,
        .timedOut, .networkConnectionLost, .internationalRoamingOff, .dataNotAllowed,
    ]

    static func isUnreachable(_ error: Error) -> Bool {
        guard let failure = error as? URLError else { return false }
        return unreachable.contains(failure.code)
    }

    static func shouldShowCachedPage(error: Error, failedURL: URL?, server: URL, gate: OfflineGate) -> Bool {
        guard isUnreachable(error) else { return false }
        if let failedURL, Endpoints.origin(failedURL) != Endpoints.origin(server) { return false }
        return gate.canShowCachedPage(for: server)
    }
}

enum OfflinePageAddress {
    static let scheme = "waypoint-offline"
    static let host = "waypoint.offline"
    static let home = URL(string: "\(scheme)://\(host)/")!
}

final class OfflinePageHandler: NSObject, WKURLSchemeHandler {
    private let server: URL
    private let gate: OfflineGate
    private let onServerRequest: () -> Void

    init(server: URL, gate: OfflineGate = .shared, onServerRequest: @escaping () -> Void = {}) {
        self.server = server
        self.gate = gate
        self.onServerRequest = onServerRequest
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url, url.scheme == OfflinePageAddress.scheme, url.host == OfflinePageAddress.host,
              (urlSchemeTask.request.httpMethod ?? "GET") == "GET" else {
            urlSchemeTask.didFailWithError(URLError(.unsupportedURL))
            return
        }
        let path = url.path.isEmpty ? OfflinePageFiles.index : url.path
        guard let data = gate.file(path, for: server) else {
            if path.hasPrefix("/api/") || path.hasPrefix("/auth/") { onServerRequest() }
            urlSchemeTask.didFailWithError(URLError(.notConnectedToInternet))
            return
        }
        let headers = ["Content-Type": OfflinePageFiles.mimeType(for: path), "Content-Length": String(data.count), "Cache-Control": "no-store"]
        guard let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers) else {
            urlSchemeTask.didFailWithError(URLError(.badServerResponse))
            return
        }
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}
}

enum LoadedAssets {
    static let script = "JSON.stringify(performance.getEntriesByType('resource').map(function (e) { return e.name; }))"

    @MainActor
    static func paths(in webView: WKWebView, server: URL) async -> [String] {
        guard let text = try? await webView.evaluateJavaScript(script) as? String,
              let names = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String] else { return [] }
        return OfflinePageFiles.assetPaths(in: names, origin: server)
    }
}

enum ServerReachability {
    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 5
        return URLSession(configuration: configuration)
    }()

    static func check(_ server: URL) async -> Bool {
        guard let (_, response) = try? await session.data(from: server), let http = response as? HTTPURLResponse else { return false }
        return http.statusCode < 500
    }
}

final class OfflineNavigation: NSObject {
    static var events: [String] = []
    private let wrapped: WKNavigationDelegate?
    private let server: URL
    private let gate: OfflineGate
    private let showCachedPage: (WKWebView) -> Void
    private let serverPageLoaded: (WKWebView) -> Void

    init(wrapping wrapped: WKNavigationDelegate?, server: URL, gate: OfflineGate = .shared,
         showCachedPage: @escaping (WKWebView) -> Void, serverPageLoaded: @escaping (WKWebView) -> Void) {
        self.wrapped = wrapped
        self.server = server
        self.gate = gate
        self.showCachedPage = showCachedPage
        self.serverPageLoaded = serverPageLoaded
    }

    override func responds(to aSelector: Selector!) -> Bool {
        super.responds(to: aSelector) || wrapped?.responds(to: aSelector) == true
    }

    override func forwardingTarget(for aSelector: Selector!) -> Any? {
        wrapped?.responds(to: aSelector) == true ? wrapped : super.forwardingTarget(for: aSelector)
    }
}

extension OfflineNavigation: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        wrapped?.webView?(webView, didFailProvisionalNavigation: navigation, withError: error)
        OfflineNavigation.events.append("fail \((error as NSError).domain) \((error as NSError).code) \(String(describing: (error as NSError).userInfo[NSURLErrorFailingURLErrorKey]))")
        let failedURL = (error as NSError).userInfo[NSURLErrorFailingURLErrorKey] as? URL
        if OfflineFallback.shouldShowCachedPage(error: error, failedURL: failedURL, server: server, gate: gate) {
            showCachedPage(webView)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        wrapped?.webView?(webView, didFinish: navigation)
        OfflineNavigation.events.append("finish \(String(describing: webView.url))")
        if let url = webView.url, Endpoints.origin(url) == Endpoints.origin(server) {
            serverPageLoaded(webView)
        }
    }
}
