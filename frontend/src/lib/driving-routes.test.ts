import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fake, fakeMk, windingPath } from "../test/fake-mapkit";
import { clearRouteCache, drivingRoute, parseRoute, ROUTE_PARALLEL } from "./driving-routes";

const from = { latitude: 39.74, longitude: -104.99 };
const to = (n: number) => ({ latitude: 40 + n / 10, longitude: -111.89 });
const road = windingPath(from, to(0)).flat();

beforeEach(() => {
  vi.useFakeTimers();
  fake.reset();
  clearRouteCache();
});
afterEach(() => { vi.useRealTimers(); });

describe("clearing the cache while requests are in flight", () => {
  it("keeps the old answers out, and keeps the limit of parallel calls for what comes next", async () => {
    fake.directions.mode = "slow";
    const old = Array.from({ length: ROUTE_PARALLEL + 2 }, (_, n) => drivingRoute(fakeMk, from, to(n)));
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.directions.calls).toHaveLength(ROUTE_PARALLEL);
    clearRouteCache();
    await vi.advanceTimersByTimeAsync(200);
    expect((await Promise.all(old)).every((r) => r === null)).toBe(true);
    expect(fake.directions.calls).toHaveLength(ROUTE_PARALLEL);

    fake.directions.mode = "ok";
    const again = drivingRoute(fakeMk, from, to(0));
    await vi.advanceTimersByTimeAsync(20);
    expect(await again).not.toBeNull();
    expect(fake.directions.calls).toHaveLength(ROUTE_PARALLEL + 1);

    fake.directions.mode = "hang";
    const calls = fake.directions.calls.length;
    for (let n = 10; n < 10 + ROUTE_PARALLEL + 3; n++) void drivingRoute(fakeMk, from, to(n));
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.directions.calls.length - calls).toBe(ROUTE_PARALLEL);
  });
});

describe("reading the answer", () => {
  const first = { latitude: 1, longitude: 2 }, second = { latitude: 3, longitude: 4 }, third = { latitude: 5, longitude: 6 };
  const pairs = [[1, 2], [3, 4], [5, 6]];

  it("takes a path of paths, a flat path, or the steps' paths", () => {
    expect(parseRoute({ path: [[first, second], [third]] })).toEqual(pairs);
    expect(parseRoute({ path: [first, second, third] })).toEqual(pairs);
    expect(parseRoute({ steps: [{ path: [first, second] }, { path: [third] }] })).toEqual(pairs);
    expect(parseRoute({ path: [], steps: [{ path: [first, second] }, { path: [[third]] }] })).toEqual(pairs);
  });

  it("takes nothing it cannot read as at least two coordinates", () => {
    expect(parseRoute(undefined)).toBeNull();
    expect(parseRoute({})).toBeNull();
    expect(parseRoute({ path: "road" })).toBeNull();
    expect(parseRoute({ path: [[first]] })).toBeNull();
    expect(parseRoute({ path: [[first, { latitude: Number.NaN, longitude: 1 }]] })).toBeNull();
    expect(parseRoute({ path: [[first, [1, 2], second]] })).toBeNull();
    expect(parseRoute({ path: [[first, { latitude: "1", longitude: 2 }]] })).toBeNull();
    expect(parseRoute({ path: [], steps: [{ path: [first] }, { path: 7 }] })).toBeNull();
    expect(parseRoute({ path: [], steps: [] })).toBeNull();
  });

  it.each(["ok", "flat", "steps"] as const)("gets the same road from the fake's %s shape", async (mode) => {
    fake.directions.mode = mode;
    const found = drivingRoute(fakeMk, from, to(0));
    await vi.advanceTimersByTimeAsync(20);
    expect(await found).toEqual(road.map((c) => [c.latitude, c.longitude]));
  });

  it.each(["malformed", "nan", "short", "mixed", "empty", "error"] as const)("gives no road for the fake's %s answer", async (mode) => {
    fake.directions.mode = mode;
    const found = drivingRoute(fakeMk, from, to(0));
    await vi.advanceTimersByTimeAsync(20);
    expect(await found).toBeNull();
  });
});
