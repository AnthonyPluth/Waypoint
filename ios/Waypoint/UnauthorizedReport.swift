import WebKit

extension Notification.Name {
    static let webViewUnauthorized = Notification.Name("WaypointWebViewUnauthorized")
}

enum UnauthorizedReport {
    static let handlerName = "waypointUnauthorized"

    static let script = """
    (function () {
      var report = function (status, url) {
        if (status !== 401) { return; }
        var path;
        try {
          var parsed = new URL(url, location.href);
          if (parsed.origin !== location.origin) { return; }
          path = parsed.pathname;
        } catch (e) { return; }
        window.webkit.messageHandlers.\(handlerName).postMessage({ status: status, path: path });
      };
      var nativeFetch = window.fetch;
      window.fetch = function () {
        var args = arguments;
        return nativeFetch.apply(this, args).then(function (response) {
          report(response.status, response.url);
          return response;
        });
      };
      var nativeSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.send = function () {
        this.addEventListener("loadend", function () { report(this.status, this.responseURL); });
        return nativeSend.apply(this, arguments);
      };
    })();
    """

    static func isSessionEnded(body: Any, origin: String, server: URL?, isMainFrame: Bool) -> Bool {
        guard isMainFrame, let server, let host = server.host else { return false }
        guard origin.lowercased() == host.lowercased() else { return false }
        guard let fields = body as? [String: Any],
              let status = fields["status"] as? Int, status == 401,
              let path = fields["path"] as? String else { return false }
        return path == "/api" || path.hasPrefix("/api/")
    }
}

final class UnauthorizedHandler: NSObject, WKScriptMessageHandler {
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        let origin = message.frameInfo.securityOrigin.host
        let isMain = message.frameInfo.isMainFrame
        Task {
            let server = await ServerSession.shared.server
            guard UnauthorizedReport.isSessionEnded(body: message.body, origin: origin, server: server, isMainFrame: isMain) else { return }
            NotificationCenter.default.post(name: .webViewUnauthorized, object: nil)
        }
    }
}
