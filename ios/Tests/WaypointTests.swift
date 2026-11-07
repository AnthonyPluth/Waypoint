import XCTest
@testable import Waypoint

final class PKCETests: XCTestCase {
    func testTheChallengeMatchesTheRFC7636Example() {
        XCTAssertEqual(PKCE.challenge(for: "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
                       "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    }

    func testAVerifierIsLongEnoughAndUsesOnlyAllowedCharacters() {
        let v = PKCE.random()
        XCTAssertTrue((43...128).contains(v.count))
        XCTAssertNil(v.rangeOfCharacter(from: CharacterSet(charactersIn: "+/=")))
        XCTAssertNotEqual(v, PKCE.random())
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
