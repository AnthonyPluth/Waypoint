import Foundation
import WebKit

enum SavedTrips {
    struct Copy {
        let savedAt: Date
        let trips: [[String: Any]]
    }

    static func read(_ store: OfflineStore, server: URL) -> Copy? {
        guard let snapshot = store.load(server: server), snapshot.version == OfflineSync.supportedVersion,
              let object = try? JSONSerialization.jsonObject(with: snapshot.json) as? [String: Any],
              let trips = object["trips"] as? [[String: Any]], !trips.isEmpty else { return nil }
        return Copy(savedAt: snapshot.savedAt, trips: trips)
    }

    static func milliseconds(_ date: Date) -> Int {
        Int((date.timeIntervalSince1970 * 1000).rounded())
    }
}

struct OfflineBridge {
    static let version = 1

    enum Failure: Error, Equatable {
        case unknownRequest
    }

    let store: OfflineStore
    let sync: OfflineSync
    let settings: OfflineSettings

    func answer(_ body: Any, server: URL) async throws -> [String: Any] {
        guard let request = body as? [String: Any], let type = request["type"] as? String else { throw Failure.unknownRequest }
        switch type {
        case "status":
            return status(server)
        case "load":
            return load(server)
        case "setSaving":
            guard let on = request["on"] as? Bool else { throw Failure.unknownRequest }
            await sync.setSaving(on)
            return status(server)
        case "remove":
            await sync.remove()
            return status(server)
        default:
            throw Failure.unknownRequest
        }
    }

    func status(_ server: URL) -> [String: Any] {
        let copy = SavedTrips.read(store, server: server)
        let trips: [[String: Any]] = (copy?.trips ?? []).compactMap { entry in
            guard let trip = entry["trip"] as? [String: Any], let id = trip["id"] as? Int, let name = trip["name"] as? String else { return nil }
            return ["id": id, "name": name]
        }
        let savedAt: Any = copy.map { SavedTrips.milliseconds($0.savedAt) } ?? NSNull()
        return ["version": Self.version, "saving": settings.isOn, "syncing": sync.state.syncing, "lastSaveFailed": sync.state.lastSaveFailed,
                "savedAt": savedAt, "trips": trips]
    }

    func load(_ server: URL) -> [String: Any] {
        guard let copy = SavedTrips.read(store, server: server) else { return ["version": Self.version, "trips": [Any]()] }
        let savedAt = SavedTrips.milliseconds(copy.savedAt)
        let trips: [[String: Any]] = copy.trips.map { entry in
            var trip = entry
            trip["savedAt"] = savedAt
            return trip
        }
        return ["version": Self.version, "trips": trips]
    }
}

enum BridgeOrigin {
    static func accepts(scheme: String, host: String, port: Int, isMainFrame: Bool, server: URL) -> Bool {
        guard isMainFrame, let serverHost = server.host?.lowercased() else { return false }
        let scheme = scheme.lowercased()
        let host = host.lowercased()
        if scheme == OfflinePageAddress.scheme { return host == OfflinePageAddress.host }
        let serverScheme = server.scheme?.lowercased() ?? ""
        return scheme == serverScheme && host == serverHost && (port == 0 ? defaultPort(scheme) : port) == (server.port ?? defaultPort(serverScheme))
    }

    private static func defaultPort(_ scheme: String) -> Int {
        scheme == "https" ? 443 : scheme == "http" ? 80 : 0
    }
}

@MainActor
final class OfflineBridgeHandler: NSObject, WKScriptMessageHandlerWithReply {
    static let name = "waypointOffline"

    private let server: URL
    private let bridge: OfflineBridge
    private let currentServer: @Sendable () async -> URL?
    private let onSavingOn: @MainActor (WKWebView) -> Void

    init(server: URL,
         bridge: OfflineBridge = OfflineBridge(store: .shared, sync: .shared, settings: OfflineSettings()),
         currentServer: @escaping @Sendable () async -> URL? = { await ServerSession.shared.server },
         onSavingOn: @escaping @MainActor (WKWebView) -> Void = { _ in }) {
        self.server = server
        self.bridge = bridge
        self.currentServer = currentServer
        self.onSavingOn = onSavingOn
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) async -> (Any?, String?) {
        let origin = message.frameInfo.securityOrigin
        guard BridgeOrigin.accepts(scheme: origin.`protocol`, host: origin.host, port: origin.port,
                                   isMainFrame: message.frameInfo.isMainFrame, server: server),
              let live = await currentServer(), Endpoints.canonical(live) == Endpoints.canonical(server) else {
            return (nil, "Saved trips are not available here.")
        }
        do {
            let reply = try await bridge.answer(message.body, server: server)
            if let request = message.body as? [String: Any], request["type"] as? String == "setSaving", request["on"] as? Bool == true,
               let webView = message.webView {
                onSavingOn(webView)
            }
            return (reply, nil)
        } catch {
            return (nil, "That request is not supported.")
        }
    }
}
