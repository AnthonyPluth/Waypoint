import { describe, expect, it } from "vitest";
import { countdown, earlyLate, timeLeft } from "./flighthero";

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

describe("the hero’s top-right words", () => {
  it("counts down in days, then hours, then minutes", () => {
    expect(countdown(3 * DAY + 2 * HOUR)).toBe("In 3 days");
    expect(countdown(DAY)).toBe("In 1 day");
    expect(countdown(5 * HOUR + 10 * MIN)).toBe("In 5 hours");
    expect(countdown(HOUR)).toBe("In 1 hour");
    expect(countdown(7 * MIN)).toBe("In 7 min");
    expect(countdown(10_000)).toBe("In 1 min");
  });

  it("says the time left in the air", () => {
    expect(timeLeft(38 * MIN)).toBe("38 min left");
    expect(timeLeft(2 * HOUR)).toBe("2 h 00 m left");
    expect(timeLeft(HOUR + 5 * MIN)).toBe("1 h 05 m left");
    expect(timeLeft(10_000)).toBe("Landing");
  });

  it("says early or on time in green and late in amber", () => {
    expect(earlyLate(-7)).toEqual({ text: "7 min early", tone: "success" });
    expect(earlyLate(0)).toEqual({ text: "On time", tone: "success" });
    expect(earlyLate(12)).toEqual({ text: "12 min late", tone: "signal" });
  });
});
