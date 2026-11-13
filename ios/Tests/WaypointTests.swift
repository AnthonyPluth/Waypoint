import XCTest
@testable import Waypoint

final class PKCETests: XCTestCase {
    func testTheChallengeMatchesTheRFC7636Example() {
        XCTAssertEqual(PKCE.challenge(for: "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
                       "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    }

    func testAVerifierIsLongEnoughAndUsesOnlyAllowedCharacters() throws {
        let v = try PKCE.random()
        XCTAssertTrue((43...128).contains(v.count))
        XCTAssertNil(v.rangeOfCharacter(from: CharacterSet(charactersIn: "+/=")))
        XCTAssertNotEqual(v, try PKCE.random())
    }

    func testFailsInsteadOfUsingZeroBytesWhenTheRandomSourceFails() {
        XCTAssertThrowsError(try PKCE.random { _, _ in errSecAllocate })
    }
}

final class ServerAddressTests: XCTestCase {
    func testAnAddressWithoutASchemeGetsHTTPS() throws {
        XCTAssertEqual(try ServerClient.normalize(" waypoint.example.com/ ").absoluteString, "https://waypoint.example.com")
    }

    func testAnHTTPAddressIsKeptForALocalServer() throws {
        XCTAssertEqual(try ServerClient.normalize("http://192.168.1.20:8080").absoluteString, "http://192.168.1.20:8080")
    }

    func testRefusesWhatIsNotAWebAddress() {
        for bad in ["", "   ", "ftp://example.com", "https://user:pw@example.com", "https://"] {
            XCTAssertThrowsError(try ServerClient.normalize(bad), bad)
        }
    }
}

final class SignInReplyTests: XCTestCase {
    private let issuer = "https://waypoint.example.com"

    func testTakesTheCodeFromAMatchingReply() throws {
        let url = URL(string: "waypoint://auth?code=wpo_abc&state=s1&iss=\(issuer)")!
        XCTAssertEqual(try SignIn.code(from: url, state: "s1", issuer: issuer), "wpo_abc")
    }

    func testRefusesAReplyForAnotherSignIn() {
        let url = URL(string: "waypoint://auth?code=wpo_abc&state=other")!
        XCTAssertThrowsError(try SignIn.code(from: url, state: "s1", issuer: issuer))
    }

    func testRefusesAReplyFromAnotherServer() {
        let url = URL(string: "waypoint://auth?code=wpo_abc&state=s1&iss=https://evil.example")!
        XCTAssertThrowsError(try SignIn.code(from: url, state: "s1", issuer: issuer))
    }

    func testRefusesAReplyWithNoIssuer() {
        let url = URL(string: "waypoint://auth?code=wpo_abc&state=s1")!
        XCTAssertThrowsError(try SignIn.code(from: url, state: "s1", issuer: issuer))
    }

    func testReportsADeniedSignIn() {
        let url = URL(string: "waypoint://auth?error=access_denied&error_description=No&state=s1")!
        XCTAssertThrowsError(try SignIn.code(from: url, state: "s1", issuer: issuer))
    }
}

final class WebDataScopeTests: XCTestCase {
    func testMatchesTheServersOwnName() {
        XCTAssertTrue(WebDataScope.covers(recordName: "waypoint.example.com", host: "waypoint.example.com"))
    }

    func testMatchesTheParentDomainRecordOfAServerOnASubdomain() {
        XCTAssertTrue(WebDataScope.covers(recordName: "example.com", host: "waypoint.example.com"))
    }

    func testMatchesASubdomainRecordOfAServerOnTheParentDomain() {
        XCTAssertTrue(WebDataScope.covers(recordName: "app.example.com", host: "example.com"))
    }

    func testIgnoresOtherSitesEvenWithASimilarName() {
        XCTAssertFalse(WebDataScope.covers(recordName: "example.org", host: "waypoint.example.com"))
        XCTAssertFalse(WebDataScope.covers(recordName: "notexample.com", host: "example.com"))
        XCTAssertFalse(WebDataScope.covers(recordName: "", host: "example.com"))
    }
}

final class EndpointBindingTests: XCTestCase {
    private let server = URL(string: "https://waypoint.example.com")!

    private func endpoints(issuer: String = "https://waypoint.example.com",
                           authorize: String = "https://waypoint.example.com/oauth/authorize",
                           token: String = "https://waypoint.example.com/oauth/token",
                           revoke: String? = "https://waypoint.example.com/oauth/revoke") -> Endpoints {
        Endpoints(issuer: issuer, authorizationEndpoint: URL(string: authorize)!, tokenEndpoint: URL(string: token)!,
                  revocationEndpoint: revoke.flatMap { URL(string: $0) })
    }

    func testAcceptsMetadataOfTheEnteredServer() throws {
        try endpoints().validate(for: server)
        try endpoints(issuer: "https://Waypoint.Example.com/", revoke: nil).validate(for: server)
    }

    func testRefusesAnIssuerThatIsNotTheEnteredServer() {
        XCTAssertThrowsError(try endpoints(issuer: "https://other.example.com").validate(for: server))
        XCTAssertThrowsError(try endpoints(issuer: "http://waypoint.example.com").validate(for: server))
    }

    func testRefusesEndpointsOutsideTheIssuer() {
        XCTAssertThrowsError(try endpoints(authorize: "https://evil.example/oauth/authorize").validate(for: server))
        XCTAssertThrowsError(try endpoints(token: "https://evil.example/oauth/token").validate(for: server))
        XCTAssertThrowsError(try endpoints(revoke: "https://evil.example/oauth/revoke").validate(for: server))
    }
}

final class PendingRevocationTests: XCTestCase {
    func testKeepsEachTokenOnceAndSurvivesEncoding() throws {
        let one = PendingRevocation(server: "https://waypoint.example.com", refreshToken: "wpr_one")
        let two = PendingRevocation(server: "https://waypoint.example.com", refreshToken: "wpr_two")
        let list = PendingRevocation.adding(one, to: PendingRevocation.adding(two, to: [one]))
        XCTAssertEqual(list, [one, two])
        XCTAssertEqual(try JSONDecoder().decode([PendingRevocation].self, from: JSONEncoder().encode(list)), list)
    }
}

final class WebSessionClockTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_000_000)

    func testNeedsRenewalWhenNoSessionWasMinted() {
        XCTAssertTrue(WebSessionClock.needsRenewal(expiresAt: nil, now: now))
    }

    func testKeepsAFreshSession() {
        XCTAssertFalse(WebSessionClock.needsRenewal(expiresAt: now.addingTimeInterval(86_400), now: now))
    }

    func testRenewsWithinTheMarginAndAfterExpiry() {
        XCTAssertTrue(WebSessionClock.needsRenewal(expiresAt: now.addingTimeInterval(120), now: now))
        XCTAssertTrue(WebSessionClock.needsRenewal(expiresAt: now.addingTimeInterval(-10), now: now))
    }
}

final class PendingRevocationRemovalTests: XCTestCase {
    private let a = PendingRevocation(server: "https://a.example", refreshToken: "wpr_a")
    private let b = PendingRevocation(server: "https://b.example", refreshToken: "wpr_b")

    func testRemovingKeepsRecordsAddedSinceTheSnapshot() {
        let latest = PendingRevocation.adding(b, to: [a])
        XCTAssertEqual(PendingRevocation.removing(a, from: latest), [b])
    }

    func testRemovingARecordThatIsGoneChangesNothing() {
        XCTAssertEqual(PendingRevocation.removing(a, from: [b]), [b])
    }
}

final class SingleFlightTests: XCTestCase {
    private actor Counter {
        var count = 0
        func next() -> Int { count += 1; return count }
    }

    func testOverlappingCallersShareOneRun() async throws {
        let flight = SingleFlight<Int>()
        let counter = Counter()
        let work: @Sendable () async throws -> Int = {
            try await Task.sleep(nanoseconds: 200_000_000)
            return await counter.next()
        }
        async let first = flight.run(work)
        async let second = flight.run(work)
        let results = try await [first, second]
        let runs = await counter.count
        XCTAssertEqual(results, [1, 1])
        XCTAssertEqual(runs, 1)
    }

    func testALaterCallerStartsANewRun() async throws {
        let flight = SingleFlight<Int>()
        let counter = Counter()
        let first = try await flight.run { await counter.next() }
        let second = try await flight.run { await counter.next() }
        XCTAssertEqual([first, second], [1, 2])
    }
}

final class LocalNetworkRetryTests: XCTestCase {
    func testRetriesAConnectionRefusedWhileThePermissionIsPending() {
        XCTAssertTrue(ServerClient.shouldRetry(.notConnectedToInternet, attempt: 0))
        XCTAssertTrue(ServerClient.shouldRetry(.cannotConnectToHost, attempt: 1))
    }

    func testGivesUpAfterTwoRetries() {
        XCTAssertFalse(ServerClient.shouldRetry(.notConnectedToInternet, attempt: 2))
    }

    func testNeverRetriesAFailureThatMayHaveReachedTheServer() {
        XCTAssertFalse(ServerClient.shouldRetry(.timedOut, attempt: 0))
        XCTAssertFalse(ServerClient.shouldRetry(.networkConnectionLost, attempt: 0))
    }
}

final class ConnectFormTests: XCTestCase {
    func testStaysDisabledWhileWorkingOrEmpty() {
        XCTAssertFalse(ConnectView.canConnect(address: "https://x.example", working: true))
        XCTAssertFalse(ConnectView.canConnect(address: "  \n", working: false))
        XCTAssertTrue(ConnectView.canConnect(address: "https://x.example", working: false))
    }
}

final class UnauthorizedReportTests: XCTestCase {
    private let server = URL(string: "https://waypoint.example.com")!

    private func ended(_ body: Any = ["status": 401, "path": "/api/trips"], origin: String = "waypoint.example.com",
                       server: URL? = URL(string: "https://waypoint.example.com"), main: Bool = true) -> Bool {
        UnauthorizedReport.isSessionEnded(body: body, origin: origin, server: server, isMainFrame: main)
    }

    func testAnApiCallAnswering401EndsTheSession() {
        XCTAssertTrue(ended())
        XCTAssertTrue(ended(["status": 401, "path": "/api/trips/12/segments"], origin: "Waypoint.Example.com"))
    }

    func testOtherStatusesAndPathsAreIgnored() {
        XCTAssertFalse(ended(["status": 403, "path": "/api/trips"]))
        XCTAssertFalse(ended(["status": 401, "path": "/oauth/token"]))
        XCTAssertFalse(ended(["status": 401, "path": "/apix"]))
    }

    func testAReportFromAnotherOriginOrFrameIsIgnored() {
        XCTAssertFalse(ended(origin: "other.example.com"))
        XCTAssertFalse(ended(main: false))
    }

    func testNothingEndsWhenNoServerIsConnected() {
        XCTAssertFalse(ended(server: nil))
    }

    func testAMalformedReportIsIgnored() {
        XCTAssertFalse(ended("401"))
        XCTAssertFalse(ended(["status": "401", "path": "/api/trips"]))
        XCTAssertFalse(ended(["status": 401]))
    }
}
