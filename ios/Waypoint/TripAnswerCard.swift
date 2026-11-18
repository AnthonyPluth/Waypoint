import SwiftUI

/// The card Siri and Shortcuts show under the spoken answer, drawn as the signed-off frames show it
/// (`docs/design/siri-shortcuts/a-answers.html`, `b-states.html`): the tokens are `frontend/src/app.css`'s dark ones.
/// A fixed answer (locked, signed out, nothing found) has no card.
struct TripAnswerCard: View {
    let answer: Answer

    var body: some View {
        if let card = answer.card {
            CardContent(card: card)
        }
    }
}

private extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255, opacity: 1)
    }
}

private enum Tokens {
    static let foreground = Color(hex: 0xf3f5f9)
    static let card = Color(hex: 0x12151d)
    static let border = Color(hex: 0x232837)
    static let muted = Color(hex: 0x9aa4b8)
    static let flight = Color(hex: 0x4f9dff)
    static let stay = Color(hex: 0x4fd1b0)
    static let infoSoft = Color(hex: 0x11233d)
    static let infoInk = Color(hex: 0x8fc2ff)
    static let warnSoft = Color(hex: 0x34270c)
    static let warnInk = Color(hex: 0xffd58a)
    static let quietSoft = Color(hex: 0x1a1e29)
}

private struct CardContent: View {
    let card: AnswerCard

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if let from = card.from, let to = card.to { route(from, to) }
            if let address = card.address {
                Text(address).font(.system(size: 14)).foregroundColor(Tokens.muted)
            }
            if let checkIn = card.checkIn, let checkOut = card.checkOut {
                HStack(alignment: .top, spacing: 16) {
                    fact("Check-in", checkIn)
                    fact("Check-out", checkOut)
                }
            }
            Divider().overlay(Tokens.border)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(card.footer)
                Spacer(minLength: 8)
                Text(card.saved).multilineTextAlignment(.trailing)
            }
            .font(.system(size: 12.5))
            .foregroundColor(Tokens.muted)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(Tokens.card, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).stroke(Tokens.border, lineWidth: 1))
        .foregroundColor(Tokens.foreground)
        .environment(\.colorScheme, .dark)
        .accessibilityElement(children: .combine)
    }

    private var tint: Color { card.kind == .flight ? Tokens.flight : Tokens.stay }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: card.kind == .flight ? "airplane" : "bed.double.fill")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(tint)
                .frame(width: 28, height: 28)
                .background(tint.opacity(0.15), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 0) {
                Text(card.eyebrow.uppercased())
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(1.3)
                    .foregroundColor(Tokens.muted)
                Text(card.title).font(.system(size: 15, weight: .semibold))
            }
            Spacer(minLength: 8)
            chip(card.chip)
        }
    }

    private func chip(_ chip: AnswerCard.Chip) -> some View {
        let (soft, ink): (Color, Color) = {
            switch chip.tone {
            case .info: return (Tokens.infoSoft, Tokens.infoInk)
            case .warn: return (Tokens.warnSoft, Tokens.warnInk)
            case .quiet: return (Tokens.quietSoft, Tokens.muted)
            }
        }()
        return HStack(spacing: 6) {
            Circle().fill(ink).frame(width: 6, height: 6)
            Text(chip.text).font(.system(size: 12, weight: .semibold)).lineLimit(1)
        }
        .foregroundColor(ink)
        .padding(.horizontal, 10)
        .padding(.vertical, 2)
        .background(soft, in: Capsule())
    }

    private func route(_ from: AnswerCard.Stop, _ to: AnswerCard.Stop) -> some View {
        HStack(alignment: .top, spacing: 12) {
            stop(from, alignment: .leading)
            ZStack {
                Rectangle()
                    .stroke(Tokens.muted.opacity(0.6), style: StrokeStyle(lineWidth: 2, dash: [4, 5]))
                    .frame(height: 2)
                Image(systemName: "airplane").font(.system(size: 14)).foregroundColor(Tokens.infoInk)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 13)
            stop(to, alignment: .trailing)
        }
    }

    private func stop(_ stop: AnswerCard.Stop, alignment: HorizontalAlignment) -> some View {
        VStack(alignment: alignment, spacing: 0) {
            Text(stop.code).font(.system(size: 28, weight: .semibold, design: .monospaced))
            if let city = stop.city {
                Text(city).font(.system(size: 13)).foregroundColor(Tokens.muted).padding(.top, 4)
            }
            (Text(stop.time).font(.system(size: 13, design: .monospaced)) + Text(" \(stop.zone)").font(.system(size: 12)).foregroundColor(Tokens.muted))
                .padding(.top, 6)
        }
    }

    private func fact(_ title: String, _ fact: AnswerCard.Fact) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title.uppercased())
                .font(.system(size: 11, weight: .semibold))
                .tracking(1.1)
                .foregroundColor(Tokens.muted)
            Text(fact.day).font(.system(size: 13.5, design: .monospaced))
            if let time = fact.time { Text(time).font(.system(size: 13.5, design: .monospaced)) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
