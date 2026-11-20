import { describe, expect, it } from "vitest";
import { segment } from "../test/fixtures";
import type { FlightCardView } from "./flightcard";
import { connectionStage, countdown, earlyLate, stopPositions, timeLeft } from "./flighthero";

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

describe("which part of a journey the hero is on", () => {
  const view = (state: string, depAt = 0, arrAt = HOUR) => ({ state, depAt, arrAt }) as unknown as FlightCardView;
  const legs = (...states: string[]) => states.map((state) => ({ segment: segment(), view: view(state) }));

  it("is before the first leg only while it is scheduled", () => {
    expect(connectionStage({ legs: legs("scheduled", "scheduled"), index: 0 })).toBe("before");
    expect(connectionStage({ legs: legs("boarding", "scheduled"), index: 0 })).toBeNull();
    expect(connectionStage({ legs: legs("in-the-air", "scheduled"), index: 0 })).toBeNull();
  });

  it("is during the connection only when the leg before has landed and this one has not left", () => {
    expect(connectionStage({ legs: legs("landed", "scheduled"), index: 1 })).toBe("during");
    expect(connectionStage({ legs: legs("scheduled", "scheduled"), index: 1 })).toBeNull();
    expect(connectionStage({ legs: legs("landed", "boarding"), index: 1 })).toBeNull();
  });

  it("is neither when any leg is cancelled or diverted, or there is only one leg", () => {
    expect(connectionStage({ legs: legs("scheduled", "cancelled"), index: 0 })).toBeNull();
    expect(connectionStage({ legs: legs("landed", "scheduled", "diverted"), index: 1 })).toBeNull();
    expect(connectionStage({ legs: legs("scheduled"), index: 0 })).toBeNull();
    expect(connectionStage(null)).toBeNull();
  });

  it("puts a single stop by how long each leg is, never at the very edge of the arc", () => {
    expect(stopPositions([view("scheduled", 0, HOUR), view("scheduled", 0, 6 * HOUR)])).toEqual([0.3]);
    expect(stopPositions([view("scheduled", 0, 4 * HOUR), view("scheduled", 0, 5 * HOUR)])[0]).toBeCloseTo(0.444, 3);
    expect(stopPositions([view("scheduled", 0, 9 * HOUR), view("scheduled", 0, HOUR)])).toEqual([0.7]);
  });

  it("spaces more stops evenly", () => {
    expect(stopPositions([view("scheduled"), view("scheduled"), view("scheduled")])).toEqual([1 / 3, 2 / 3]);
  });
});
