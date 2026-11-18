import Foundation

/// What a Siri or Shortcuts question gets back: the words Siri says, the fields of the card under them and the page the card opens.
/// Everything here is a pure function of the saved trips, the clock and the phone's time zone. No network, no `URLSession`,
/// no `ServerClient`, no Keychain.
struct AnswerCard: Equatable {
    enum Kind: Equatable { case flight, stay }
    enum Tone: Equatable { case info, warn, quiet }

    struct Chip: Equatable {
        let text: String
        let tone: Tone
    }

    struct Stop: Equatable {
        let code: String
        let city: String?
        let time: String
        let zone: String
    }

    struct Fact: Equatable {
        let day: String
        let time: String?
    }

    let kind: Kind
    let eyebrow: String
    let title: String
    let chip: Chip
    let from: Stop?
    let to: Stop?
    let address: String?
    let checkIn: Fact?
    let checkOut: Fact?
    let footer: String
    let saved: String

    /// Every piece of text the card shows, for the tests that look for values that must never appear.
    var texts: [String] {
        var all = [eyebrow, title, chip.text, footer, saved]
        for stop in [from, to].compactMap({ $0 }) {
            all += [stop.code, stop.time, stop.zone]
            if let city = stop.city { all.append(city) }
        }
        if let address { all.append(address) }
        for fact in [checkIn, checkOut].compactMap({ $0 }) {
            all.append(fact.day)
            if let time = fact.time { all.append(time) }
        }
        return all
    }
}

struct Answer: Equatable {
    enum Kind: Equatable {
        case flight, stay, noFlight, noStay, parking, noParking
        case locked, notSignedIn, savingOff, nothingSaved, unreadable
    }

    let kind: Kind
    let spoken: String
    let card: AnswerCard?
    /// The web app's hash route the card opens, such as `#trip/3` or `#trip/3/flight/12`.
    let page: String?

    static func fixed(_ kind: Kind, _ spoken: String) -> Answer {
        Answer(kind: kind, spoken: spoken, card: nil, page: nil)
    }

    static let locked = fixed(.locked, "Unlock your iPhone to see your trips in Waypoint.")
    static let notSignedIn = fixed(.notSignedIn, "Sign in to Waypoint on this iPhone first.")
    static let savingOff = fixed(.savingOff, "Saving trips is off on this iPhone. You can switch it on in Waypoint's Settings.")
    static let nothingSaved = fixed(.nothingSaved, "No trips are saved on this iPhone yet. Open Waypoint while you're online to save them.")
    static let unreadable = fixed(.unreadable, "Waypoint can't read the trips saved on this iPhone. Open the app to save them again.")
    static let noFlight = fixed(.noFlight, "There's no upcoming flight in the trips saved on this iPhone.")
    static let noStayTonight = fixed(.noStay, "There's no stay tonight or later in the trips saved on this iPhone.")
    static let noStayToCheckOutOf = fixed(.noStay, "There's no stay to check out of in the trips saved on this iPhone.")
    static let noParking = fixed(.noParking, "There's no parking in the trips saved on this iPhone.")
}

/// A booking's wall-clock time as the saved copy holds it (`2026-12-01T19:00`): never converted, only compared with another
/// wall-clock time of the same place.
struct WallClock: Equatable {
    let year: Int
    let month: Int
    let day: Int
    let hour: Int
    let minute: Int

    init(year: Int, month: Int, day: Int, hour: Int, minute: Int) {
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
    }

    init?(_ text: String) {
        let halves = text.split(whereSeparator: { $0 == "T" || $0 == " " })
        guard halves.count == 2 else { return nil }
        let date = halves[0].split(separator: "-", omittingEmptySubsequences: false).map { Int($0) }
        let time = halves[1].split(separator: ":", omittingEmptySubsequences: false).map { Int($0) }
        guard date.count == 3, time.count >= 2,
              let year = date[0], let month = date[1], let day = date[2], let hour = time[0], let minute = time[1],
              (1...12).contains(month), (1...31).contains(day), (0...23).contains(hour), (0...59).contains(minute) else { return nil }
        self.init(year: year, month: month, day: day, hour: hour, minute: minute)
    }

    /// Whole days since 1970-01-01 of this calendar day, for counting days between two dates.
    var dayNumber: Int {
        let shifted = month <= 2 ? year - 1 : year
        let era = (shifted >= 0 ? shifted : shifted - 399) / 400
        let yearOfEra = shifted - era * 400
        let dayOfYear = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1
        let dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
        return era * 146_097 + dayOfEra - 719_468
    }

    /// 0 is Sunday.
    var weekday: Int { ((dayNumber % 7) + 7 + 4) % 7 }
}

private enum Words {
    static let weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    static let months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    static func weekday(_ wall: WallClock) -> String { weekdays[wall.weekday] }
    static func monthDay(_ wall: WallClock) -> String { "\(months[wall.month - 1]) \(wall.day)" }
    static func short(_ wall: WallClock) -> String {
        "\(weekdays[wall.weekday].prefix(3)) \(months[wall.month - 1].prefix(3)) \(wall.day)"
    }

    static func two(_ value: Int) -> String { value < 10 ? "0\(value)" : "\(value)" }

    private static func parts(_ hour: Int) -> (Int, String) { (hour % 12 == 0 ? 12 : hour % 12, hour < 12 ? "am" : "pm") }

    /// "7:40 am", and "11 am" on the hour: how Siri says it.
    static func spokenTime(_ wall: WallClock) -> String {
        let (hour, suffix) = parts(wall.hour)
        return wall.minute == 0 ? "\(hour) \(suffix)" : "\(hour):\(two(wall.minute)) \(suffix)"
    }

    /// "7:40 am" and "11:00 am": how the card shows it.
    static func cardTime(_ wall: WallClock) -> String {
        let (hour, suffix) = parts(wall.hour)
        return "\(hour):\(two(wall.minute)) \(suffix)"
    }

    static func count(_ value: Int, _ unit: String) -> String { value == 1 ? "1 \(unit)" : "\(value) \(unit)s" }
}

/// A day as Siri says it: today, tomorrow, the weekday within a week, else the date.
private struct DayWord {
    let bare: String
    let relative: Bool
    let today: Bool

    /// "on Thursday", "on June 20", but "today" and "tomorrow" alone.
    var on: String { relative ? bare : "on \(bare)" }

    init(_ date: WallClock, today now: WallClock) {
        let difference = date.dayNumber - now.dayNumber
        switch difference {
        case 0:
            bare = "today"
            relative = true
        case 1:
            bare = "tomorrow"
            relative = true
        case 2...6:
            bare = Words.weekday(date)
            relative = false
        default:
            bare = Words.monthDay(date)
            relative = false
        }
        today = difference == 0
    }
}

struct TripAnswers {
    /// A copy older than this is called old on the card.
    static let oldAfter: TimeInterval = 24 * 3600

    let now: Date
    /// Its time zone is only the fallback for a booking whose zone the phone doesn't know.
    let calendar: Calendar

    init(now: Date, calendar: Calendar = .current) {
        self.now = now
        self.calendar = calendar
    }

    // MARK: Next flight

    private struct Flight {
        let trip: SavedTrip
        let booking: SavedBooking
        let start: WallClock
        let end: WallClock?
        let startZone: TimeZone
        let endZone: TimeZone
        let departs: Date
    }

    func nextFlight(_ copy: SavedCopy) -> Answer {
        var flights: [Flight] = []
        for trip in copy.trips {
            for booking in trip.bookings where booking.kind == "flight" && !booking.isCancelled && !booking.datedOnly {
                guard let start = WallClock(booking.startLocal) else { continue }
                let startZone = zone(booking.startZone)
                guard let departs = instant(start, in: startZone), departs > now else { continue }
                flights.append(Flight(trip: trip, booking: booking, start: start, end: WallClock(booking.endLocal),
                                      startZone: startZone, endZone: zone(booking.endZone), departs: departs))
            }
        }
        guard let next = flights.min(by: { ($0.departs, $0.trip.id, $0.booking.id) < ($1.departs, $1.trip.id, $1.booking.id) }) else {
            return .noFlight
        }
        return flightAnswer(next, copy: copy)
    }

    private func flightAnswer(_ flight: Flight, copy: SavedCopy) -> Answer {
        let booking = flight.booking
        let today = wall(of: now, in: flight.startZone)
        let day = DayWord(flight.start, today: today)
        let time = Words.spokenTime(flight.start)
        let number = clean(booking.flightNumber)
        let fromCode = clean(booking.origin)
        let toCode = clean(booking.destination)
        let fromCity = fromCode.flatMap { clean(flight.trip.cities[$0]) }
        let toCity = toCode.flatMap { clean(flight.trip.cities[$0]) }

        var spoken: String
        if let fromCity, let toCity {
            spoken = "Your \(day.today ? "" : "next ")flight leaves \(fromCity) for \(toCity) \(day.on) at \(time), local time"
        } else if let number {
            spoken = "Your \(day.today ? "" : "next ")flight, \(number), leaves \(day.bare) at \(time), local time"
        } else {
            spoken = "Your \(day.today ? "" : "next ")flight leaves \(day.bare) at \(time), local time"
        }
        let minutes = Int(flight.departs.timeIntervalSince(now) / 60)
        if day.today {
            spoken += minutes < 60 ? ", in \(Words.count(max(minutes, 1), "minute"))" : ", in \(Words.count(minutes / 60, "hour"))"
        }
        spoken += "."

        let age = Age(savedAt: copy.savedAt, now: now)
        let chip: AnswerCard.Chip
        if age.isOld {
            chip = .init(text: "Old copy", tone: .warn)
        } else if day.today {
            chip = .init(text: minutes < 60 ? "In \(max(minutes, 1)) min" : "In \(minutes / 60) h", tone: .info)
        } else {
            chip = .init(text: "Booked times", tone: .quiet)
        }

        let arrival = flight.end
        let card = AnswerCard(
            kind: .flight,
            eyebrow: "Next flight · \(day.today ? "Today" : Words.short(flight.start))",
            title: number ?? "Flight",
            chip: chip,
            from: .init(code: fromCode ?? "", city: fromCity, time: Words.cardTime(flight.start),
                        zone: abbreviation(flight.startZone, at: flight.departs)),
            to: .init(code: toCode ?? "", city: toCity, time: arrival.map(Words.cardTime) ?? "",
                      zone: abbreviation(flight.endZone, at: arrival.flatMap { instant($0, in: flight.endZone) } ?? flight.departs)),
            address: nil, checkIn: nil, checkOut: nil,
            footer: "Trip: \(flight.trip.name)",
            saved: age.card)
        return Answer(kind: .flight, spoken: spoken, card: card, page: "#trip/\(flight.trip.id)/flight/\(booking.id)")
    }

    // MARK: Stays

    private struct Stay {
        let trip: SavedTrip
        let booking: SavedBooking
        let start: WallClock
        let end: WallClock
        let zone: TimeZone
        let checkIn: Date
        let checkOut: Date
        let timed: Bool

        var name: String { clean(booking.origin) ?? clean(booking.provider) ?? "your hotel" }
        var order: (Date, Int, Int) { (checkOut, trip.id, booking.id) }
    }

    private func stays(_ copy: SavedCopy) -> [Stay] {
        var found: [Stay] = []
        for trip in copy.trips {
            for booking in trip.bookings where booking.kind == "hotel" && !booking.isCancelled {
                guard let start = WallClock(booking.startLocal), let end = WallClock(booking.endLocal) else { continue }
                let place = zone(booking.startZone)
                guard let checkIn = instant(start, in: place), let checkOut = instant(end, in: zone(booking.endZone)) else { continue }
                found.append(Stay(trip: trip, booking: booking, start: start, end: end, zone: place,
                                  checkIn: checkIn, checkOut: checkOut, timed: !booking.datedOnly))
            }
        }
        return found
    }

    /// Tonight is today in the hotel's own zone: check-in day on or before today, check-out day after it. Else the next saved stay.
    func tonight(_ copy: SavedCopy) -> Answer {
        let all = stays(copy)
        let tonight = all.filter { stay in
            let today = wall(of: now, in: stay.zone)
            return stay.start.dayNumber <= today.dayNumber && stay.end.dayNumber > today.dayNumber
        }
        if let stay = tonight.min(by: { $0.order < $1.order }) {
            let today = wall(of: now, in: stay.zone)
            let city = clean(stay.booking.destination).map { " in \($0)" } ?? ""
            let leaving = DayWord(stay.end, today: today)
            let when = stay.timed ? "\(leaving.bare) at \(Words.spokenTime(stay.end))" : leaving.bare
            let spoken = "Tonight you're staying at \(stay.name)\(city). You check out \(when)."
            return stayAnswer(stay, copy: copy, spoken: spoken, eyebrow: "Tonight", chip: nightChip(stay, today: today))
        }
        return nextStay(all, copy: copy, intro: "You have no stay tonight.", none: .noStayTonight) { stay in
            stay.start.dayNumber > wall(of: now, in: stay.zone).dayNumber
        }
    }

    /// Check-out is the stay under way now, from its check-in time until its check-out time, as wall-clock times in the hotel's zone.
    /// A stay with no times is under way from its check-in day to the end of its check-out day. With two under way, the one that
    /// checks out first. Past the check-out time, or with none under way, it is the next saved stay.
    func checkOut(_ copy: SavedCopy) -> Answer {
        let all = stays(copy)
        let underWay = all.filter { stay in
            let today = wall(of: now, in: stay.zone)
            if stay.timed { return stay.checkIn <= now && now < stay.checkOut }
            return stay.start.dayNumber <= today.dayNumber && today.dayNumber <= stay.end.dayNumber
        }
        if let stay = underWay.min(by: { $0.order < $1.order }) {
            let today = wall(of: now, in: stay.zone)
            let leaving = DayWord(stay.end, today: today)
            let when = stay.timed ? "\(leaving.on) at \(Words.spokenTime(stay.end))" : leaving.on
            let spoken = "You check out of \(stay.name) \(when)."
            let eyebrow = leaving.today ? "Check-out today" : "Check-out \(leaving.bare)"
            let chip = leaving.today ? AnswerCard.Chip(text: "Check-out day", tone: .info) : nightChip(stay, today: today)
            return stayAnswer(stay, copy: copy, spoken: spoken, eyebrow: eyebrow, chip: chip)
        }
        return nextStay(all, copy: copy, intro: "You're not checked in anywhere right now.", none: .noStayToCheckOutOf) { stay in
            stay.timed ? stay.checkIn > now : stay.start.dayNumber > wall(of: now, in: stay.zone).dayNumber
        }
    }

    private func nextStay(_ all: [Stay], copy: SavedCopy, intro: String, none: Answer, matching isLater: (Stay) -> Bool) -> Answer {
        guard let stay = all.filter(isLater).min(by: { ($0.checkIn, $0.trip.id, $0.booking.id) < ($1.checkIn, $1.trip.id, $1.booking.id) }) else {
            return none
        }
        let today = wall(of: now, in: stay.zone)
        let from = DayWord(stay.start, today: today)
        let nights = max(stay.end.dayNumber - stay.start.dayNumber, 1)
        let chip = AnswerCard.Chip(text: Words.count(nights, "night"), tone: .info)
        return stayAnswer(stay, copy: copy, spoken: "\(intro) Your next stay is \(stay.name), from \(from.bare).", eyebrow: "Next stay", chip: chip)
    }

    private func nightChip(_ stay: Stay, today: WallClock) -> AnswerCard.Chip {
        let nights = max(stay.end.dayNumber - stay.start.dayNumber, 1)
        let night = min(max(today.dayNumber - stay.start.dayNumber + 1, 1), nights)
        return .init(text: "Night \(night) of \(nights)", tone: .info)
    }

    private func stayAnswer(_ stay: Stay, copy: SavedCopy, spoken: String, eyebrow: String, chip: AnswerCard.Chip) -> Answer {
        let age = Age(savedAt: copy.savedAt, now: now)
        let shown = age.isOld ? AnswerCard.Chip(text: "Old copy", tone: .warn) : chip
        let card = AnswerCard(
            kind: .stay,
            eyebrow: eyebrow,
            title: stay.name,
            chip: shown,
            from: nil, to: nil,
            address: clean(stay.booking.address),
            checkIn: .init(day: Words.short(stay.start), time: stay.timed ? Words.cardTime(stay.start) : nil),
            checkOut: .init(day: Words.short(stay.end), time: stay.timed ? Words.cardTime(stay.end) : nil),
            footer: "\(abbreviation(stay.zone, at: stay.checkIn)), the hotel's time",
            saved: age.card)
        return Answer(kind: .stay, spoken: spoken, card: card, page: "#trip/\(stay.trip.id)")
    }

    // MARK: Parking

    private struct Parking {
        let trip: SavedTrip
        let booking: SavedBooking
        let start: WallClock
        let end: WallClock
        let zone: TimeZone
        let entry: Date
        let exit: Date
        let timed: Bool

        var lot: String { clean(booking.origin) ?? clean(booking.provider) ?? "Parking" }
    }

    /// The parking booking that is current (its entry passed and its exit not yet, as wall-clock times in the lot's zone; one with no
    /// times from its first day to the end of its last), the one that ends first if two are; else the next one. Not cancelled. The
    /// answer is only the lot's name and the trip to open: the code comes from the server once the app is open, never from here.
    func parking(_ copy: SavedCopy) -> Answer {
        var found: [Parking] = []
        for trip in copy.trips {
            for booking in trip.bookings where booking.kind == "parking" && !booking.isCancelled {
                guard let start = WallClock(booking.startLocal), let end = WallClock(booking.endLocal) else { continue }
                let place = zone(booking.startZone)
                guard let entry = instant(start, in: place), let exit = instant(end, in: zone(booking.endZone)) else { continue }
                found.append(Parking(trip: trip, booking: booking, start: start, end: end, zone: place,
                                     entry: entry, exit: exit, timed: !booking.datedOnly))
            }
        }
        let current = found.filter { booking in
            if booking.timed { return booking.entry <= now && now < booking.exit }
            let today = wall(of: now, in: booking.zone)
            return booking.start.dayNumber <= today.dayNumber && today.dayNumber <= booking.end.dayNumber
        }
        let next = found.filter { booking in
            booking.timed ? booking.entry > now : booking.start.dayNumber > wall(of: now, in: booking.zone).dayNumber
        }
        let chosen = current.min(by: { ($0.exit, $0.trip.id, $0.booking.id) < ($1.exit, $1.trip.id, $1.booking.id) })
            ?? next.min(by: { ($0.entry, $0.trip.id, $0.booking.id) < ($1.entry, $1.trip.id, $1.booking.id) })
        guard let chosen else { return .noParking }
        return Answer(kind: .parking, spoken: "Opening your parking at \(chosen.lot).", card: nil, page: "#trip/\(chosen.trip.id)")
    }

    // MARK: Time zones

    private func zone(_ identifier: String) -> TimeZone {
        TimeZone(identifier: identifier) ?? calendar.timeZone
    }

    private func gregorian(_ zone: TimeZone) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        return calendar
    }

    /// The moment a wall-clock time is in a zone. Used to order and to compare with now, never to show.
    private func instant(_ wall: WallClock, in zone: TimeZone) -> Date? {
        gregorian(zone).date(from: DateComponents(year: wall.year, month: wall.month, day: wall.day, hour: wall.hour, minute: wall.minute))
    }

    private func wall(of date: Date, in zone: TimeZone) -> WallClock {
        let parts = gregorian(zone).dateComponents([.year, .month, .day, .hour, .minute], from: date)
        return WallClock(year: parts.year ?? 1970, month: parts.month ?? 1, day: parts.day ?? 1, hour: parts.hour ?? 0, minute: parts.minute ?? 0)
    }

    private func abbreviation(_ zone: TimeZone, at date: Date) -> String {
        zone.abbreviation(for: date) ?? zone.identifier
    }

    // MARK: Age of the saved copy

    struct Age {
        let seconds: TimeInterval

        init(savedAt: Date, now: Date) {
            seconds = max(now.timeIntervalSince(savedAt), 0)
        }

        var isOld: Bool { seconds >= TripAnswers.oldAfter }

        /// "Saved 2 hours ago"; for an old copy it says to open Waypoint.
        var card: String {
            let minutes = Int(seconds / 60)
            let text: String
            if minutes < 1 {
                text = "Saved just now"
            } else if minutes < 60 {
                text = "Saved \(minutes) min ago"
            } else if minutes < 24 * 60 {
                text = "Saved \(Words.count(minutes / 60, "hour")) ago"
            } else {
                text = "Saved \(Words.count(minutes / (24 * 60), "day")) ago"
            }
            return isOld ? "\(text) · open Waypoint to update" : text
        }
    }
}

private func clean(_ text: String?) -> String? {
    guard let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else { return nil }
    return trimmed
}
