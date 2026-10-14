import { afterEach, describe, expect, it } from "vitest";
import { freezeDemoClock } from "./clock";
import data from "./data.json";

const SystemDate = Date;
afterEach(() => { globalThis.Date = SystemDate; });

describe("static demo clock", () => {
  it("keeps upcoming trips available after the last bundled itinerary ends", () => {
    globalThis.Date = new Proxy(SystemDate, {
      get(target, property, receiver) {
        return property === "now" ? () => SystemDate.parse("2040-01-01T00:00:00Z") : Reflect.get(target, property, receiver);
      },
    });
    freezeDemoClock(data.asOf);
    expect(Date.now()).toBe(SystemDate.parse(`${data.asOf}T12:00:00Z`));
    expect(new Date().toISOString()).toBe(`${data.asOf}T12:00:00.000Z`);
    expect(data.trips.some(trip => trip.start_date > new Date().toISOString().slice(0, 10))).toBe(true);
    expect(data.trips.some(trip => trip.end_date < new Date().toISOString().slice(0, 10))).toBe(true);
  });

  it("preserves explicit itinerary dates and date arithmetic", () => {
    freezeDemoClock(data.asOf);
    expect(new Date("2027-01-17T10:00:00Z").toISOString()).toBe("2027-01-17T10:00:00.000Z");
    expect(new Date(2030, 5, 10).getFullYear()).toBe(2030);
    expect(Date.UTC(2030, 0, 1)).toBe(SystemDate.UTC(2030, 0, 1));
    expect(Date()).toBe(new SystemDate(`${data.asOf}T12:00:00Z`).toString());
    expect(new Date()).toBeInstanceOf(SystemDate);
  });
});
