import { describe, expect, it } from "vitest";
import { amountText, countNote, formatMoney, formatTotals, toMinor } from "./money";

describe("showing money", () => {
  it("formats an amount in its own currency from the smallest unit", () => {
    expect(formatMoney(124000, "USD")).toMatch(/\$1,240\.00/);
    expect(formatMoney(31000, "EUR")).toMatch(/€310\.00/);
    expect(formatMoney(12300, "JPY")).toMatch(/12,300/);
    expect(formatMoney(12345, "KWD")).toMatch(/12\.345/);
  });
  it("shows a code Intl doesn’t know as the amount and the code", () => {
    expect(formatMoney(1250, "ZZZZ")).toBe("12.50 ZZZZ");
  });
  it("joins a trip’s totals per currency with a plus, never converting", () => {
    const text = formatTotals([{ currency: "USD", amount_minor: 124000 }, { currency: "EUR", amount_minor: 31000 }]);
    expect(text).toMatch(/^\$1,240\.00 \+ €310\.00$/);
  });
  it("says how many bookings have a cost only when some don’t", () => {
    expect(countNote({ totals: [], priced: 3, bookings: 5 })).toBe("3 of 5 bookings");
    expect(countNote({ totals: [], priced: 0, bookings: 1 })).toBe("0 of 1 booking");
    expect(countNote({ totals: [], priced: 2, bookings: 2 })).toBeNull();
  });
});

describe("reading an amount typed in the form", () => {
  it.each([
    ["1240", "USD", 124000],
    ["1240.5", "USD", 124050],
    ["1,240.00", "USD", 124000],
    ["$1,234.56", "USD", 123456],
    ["1.234,56", "EUR", 123456],
    ["1 234,56 €", "EUR", 123456],
    ["1,234", "USD", 123400],
    ["1.234", "EUR", 123400],
    ["12,5", "EUR", 1250],
    ["12,300", "JPY", 12300],
    ["12.345", "KWD", 12345],
    ["0", "USD", 0],
  ])("reads %s as %s: %i", (text, currency, minor) => {
    expect(toMinor(text, currency)).toBe(minor);
  });
  it.each(["", "abc", "-5", "(5.00)", "1.2.3", "1,23,456", "12.3456", "1e5", "99999999999", "1,,5"])("refuses %j", (text) => {
    expect(toMinor(text, "USD")).toBeNull();
  });
  it("writes an amount back the way the form reads it", () => {
    expect(amountText(124050, "USD")).toBe("1240.50");
    expect(amountText(12300, "JPY")).toBe("12300");
    expect(toMinor(amountText(31000, "EUR"), "EUR")).toBe(31000);
  });
});
