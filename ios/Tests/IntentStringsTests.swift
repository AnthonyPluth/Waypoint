import AppIntents
import XCTest
@testable import Waypoint

final class IntentStringsTests: XCTestCase {
    private static let banned = ["iphone", "ipad", "ipod", "apple", "siri", "watch"]

    private func bannedWords(in text: String) -> [String] {
        let lowered = text.lowercased()
        return Self.banned.filter { lowered.contains($0) }
    }

    private func text(_ resource: LocalizedStringResource) -> String {
        String(localized: resource)
    }

    private func intentsSource() throws -> String {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Waypoint/WaypointIntents.swift")
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func matches(_ pattern: String, in source: String) throws -> [String] {
        let regex = try NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators])
        let range = NSRange(source.startIndex..., in: source)
        return regex.matches(in: source, range: range).compactMap { match in
            Range(match.range(at: 1), in: source).map { String(source[$0]) }
        }
    }

    func testTheIntentDescriptionsNameNoDeviceOrAppleProduct() {
        let descriptions = [
            text(NextFlightIntent.description.descriptionText),
            text(TonightStayIntent.description.descriptionText),
            text(CheckOutIntent.description.descriptionText),
        ]
        for description in descriptions {
            XCTAssertFalse(description.isEmpty)
            XCTAssertEqual(bannedWords(in: description), [], description)
        }
    }

    func testTheIntentTitlesNameNoDeviceOrAppleProduct() {
        let titles = [
            text(NextFlightIntent.title),
            text(TonightStayIntent.title),
            text(CheckOutIntent.title),
        ]
        for title in titles {
            XCTAssertEqual(bannedWords(in: title), [], title)
        }
    }

    func testNoDescriptionTitleShortTitleOrPhraseInTheIntentsFileNamesADeviceOrAppleProduct() throws {
        let source = try intentsSource()
        let descriptions = try matches(#"IntentDescription\(\s*"((?:[^"\\]|\\.)*)""#, in: source)
        let titles = try matches(#"static var title[^=\n]*=\s*"((?:[^"\\]|\\.)*)""#, in: source)
        let shortTitles = try matches(#"shortTitle:\s*"((?:[^"\\]|\\.)*)""#, in: source)
        let phraseLists = try matches(#"phrases:\s*\[(.*?)\]"#, in: source)
        let phrases = try phraseLists.flatMap { try matches(#""((?:[^"\\]|\\.)*)""#, in: $0) }
        XCTAssertGreaterThanOrEqual(descriptions.count, 3)
        XCTAssertGreaterThanOrEqual(titles.count, 3)
        XCTAssertGreaterThanOrEqual(shortTitles.count, 3)
        XCTAssertGreaterThanOrEqual(phrases.count, 3)
        for string in descriptions + titles + shortTitles + phrases {
            XCTAssertEqual(bannedWords(in: string), [], string)
        }
    }
}
