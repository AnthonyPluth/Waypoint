import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fake, fakeMk, windingPath } from "../test/fake-mapkit";
import { apiCall } from "./contract";
import { CARD_POINTS, CARD_TRIPS, CARD_WAIT_MS, clearRouteCache, drivingRoute, drivingRoutes, hasDrive, parseRoute, savedRoads, savedRoutes, LOOKUP_TIMEOUT_MS, ROUTE_PARALLEL, SERVER_MAX_DRIVES, SERVER_MAX_POINTS, thin } from "./driving-routes";

vi.mock("./contract", () => ({ apiCall: vi.fn() }));
const server = vi.mocked(apiCall);

const from = { latitude: 39.74, longitude: -104.99 };
const to = (n: number) => ({ latitude: 40 + n / 10, longitude: -111.89 });
const road = windingPath(from, to(0)).flat();

beforeEach(() => {
  vi.useFakeTimers();
  fake.reset();
  clearRouteCache();
  server.mockReset();
  server.mockResolvedValue({ routes: [] });
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

describe("the household's stored routes", () => {
  const trip = 7;
  const drive = (n: number) => ({ from, to: to(n) });
  const stored = (n: number, path = road.map((c) => [c.latitude, c.longitude])) => ({ start: from, end: to(n), path });
  const settle = () => vi.advanceTimersByTimeAsync(50);
  const gets = () => server.mock.calls.filter(([, options]) => options?.method !== "PUT");
  const puts = () => server.mock.calls.filter(([, options]) => options?.method === "PUT");

  it("asks the server once for every drive, takes its paths, and asks MapKit for none", async () => {
    server.mockResolvedValue({ routes: [stored(0), stored(1), stored(2)] });
    const answers = drivingRoutes(fakeMk, trip, [drive(0), drive(1), drive(2)]);
    await settle();
    expect((await Promise.all(answers)).every((r) => r?.length === road.length)).toBe(true);
    expect(gets()).toHaveLength(1);
    expect(gets()[0][0]).toBe(`/api/trips/7/driving-routes?drive=39.7400,-104.9900,40.0000,-111.8900&drive=39.7400,-104.9900,40.1000,-111.8900&drive=39.7400,-104.9900,40.2000,-111.8900`);
    expect(fake.directions.calls).toHaveLength(0);
    expect(puts()).toHaveLength(0);
  });

  it("asks MapKit for a drive the server has not stored, then sends that path to the server once", async () => {
    const answers = drivingRoutes(fakeMk, trip, [drive(0)]);
    await settle();
    const path = await answers[0];
    expect(path).toEqual(road.map((c) => [c.latitude, c.longitude]));
    expect(fake.directions.calls).toHaveLength(1);
    expect(puts()).toHaveLength(1);
    expect(puts()[0][0]).toBe("/api/trips/7/driving-routes");
    expect(puts()[0][1]).toMatchObject({ method: "PUT", body: { start: { latitude: 39.74, longitude: -104.99 }, end: { latitude: 40, longitude: -111.89 }, path } });
    const again = drivingRoutes(fakeMk, trip, [drive(0)])[0];
    await settle();
    await again;
    expect(fake.directions.calls).toHaveLength(1);
    expect(gets()).toHaveLength(1);
    expect(puts()).toHaveLength(1);
  });

  it("stores a row for a second trip over a drive already in memory, once, without asking MapKit again", async () => {
    const first = drivingRoutes(fakeMk, trip, [drive(0)])[0];
    await settle();
    const path = await first;
    expect(puts().map(([url]) => url)).toEqual(["/api/trips/7/driving-routes"]);
    const second = Promise.all([drivingRoutes(fakeMk, 8, [drive(0)])[0], drivingRoutes(fakeMk, 8, [drive(0)])[0]]);
    await settle();
    expect(await second).toEqual([path, path]);
    expect(fake.directions.calls).toHaveLength(1);
    expect(puts().map(([url]) => url)).toEqual(["/api/trips/7/driving-routes", "/api/trips/8/driving-routes"]);
    expect(puts()[1][1]).toMatchObject({ body: { path } });
    const third = drivingRoutes(fakeMk, 8, [drive(0)])[0];
    await settle();
    await third;
    expect(puts()).toHaveLength(2);
  });

  it("stores a row for a second trip that asks for a drive the first is still waiting on", async () => {
    fake.directions.mode = "slow";
    const answers = [drivingRoutes(fakeMk, trip, [drive(0)])[0], drivingRoutes(fakeMk, 8, [drive(0)])[0]];
    await vi.advanceTimersByTimeAsync(300);
    await Promise.all(answers);
    expect(fake.directions.calls).toHaveLength(1);
    expect(puts().map(([url]) => url).sort()).toEqual(["/api/trips/7/driving-routes", "/api/trips/8/driving-routes"]);
  });

  it("sends a trip's row again after a failed send, and a trip already on the server nothing", async () => {
    let refuse = true;
    server.mockImplementation(((_path: string, options?: { method?: string }) => options?.method === "PUT" ? (refuse ? Promise.reject(new Error("refused")) : Promise.resolve({})) : Promise.resolve({ routes: [] })) as never);
    const first = drivingRoutes(fakeMk, trip, [drive(0)])[0];
    await settle();
    await first;
    refuse = false;
    const again = drivingRoutes(fakeMk, trip, [drive(0)])[0];
    await settle();
    await again;
    expect(puts()).toHaveLength(2);
    server.mockClear();
    server.mockResolvedValue({ routes: [stored(1)] });
    const stored1 = drivingRoutes(fakeMk, 9, [drive(1)])[0];
    await settle();
    await stored1;
    const reopened = drivingRoutes(fakeMk, 9, [drive(1)])[0];
    await settle();
    await reopened;
    expect(puts()).toHaveLength(0);
  });

  it("only asks the server about what is missing, and only once per replay", async () => {
    server.mockResolvedValue({ routes: [stored(0)] });
    const first = Promise.all(drivingRoutes(fakeMk, trip, [drive(0), drive(1)]));
    await settle();
    await first;
    expect(gets()).toHaveLength(1);
    server.mockClear();
    const again = Promise.all(drivingRoutes(fakeMk, trip, [drive(0), drive(1)]));
    await settle();
    await again;
    expect(server).not.toHaveBeenCalled();
    const more = Promise.all(drivingRoutes(fakeMk, trip, [drive(0), drive(1), drive(2)]));
    await settle();
    await more;
    expect(gets()).toHaveLength(1);
    expect(gets()[0][0]).toBe("/api/trips/7/driving-routes?drive=39.7400,-104.9900,40.2000,-111.8900");
  });

  it("does not ask the server when it has no trip to ask about", async () => {
    const answers = drivingRoutes(fakeMk, null, [drive(0)]);
    await settle();
    expect(await answers[0]).not.toBeNull();
    expect(server).not.toHaveBeenCalled();
    expect(fake.directions.calls).toHaveLength(1);
  });

  it("asks MapKit exactly as before when the server cannot be reached", async () => {
    server.mockRejectedValue(new Error("offline"));
    const answers = drivingRoutes(fakeMk, trip, [drive(0), drive(1)]);
    await settle();
    expect((await Promise.all(answers)).every((r) => r !== null)).toBe(true);
    expect(fake.directions.calls).toHaveLength(2);
  });

  it.each([
    ["nothing", undefined], ["a string", { routes: "x" }], ["no routes", {}], ["a short path", { routes: [{ start: from, end: to(0), path: [[1, 2]] }] }],
    ["a path of text", { routes: [{ start: from, end: to(0), path: [["a", "b"], ["c", "d"]] }] }], ["a path with a gap", { routes: [{ start: from, end: to(0), path: [[1, 2], [Number.NaN, 4]] }] }],
    ["no places", { routes: [{ path: [[1, 2], [3, 4]] }] }],
  ])("asks MapKit when the server answers with %s", async (_name, reply) => {
    server.mockResolvedValue(reply as never);
    const answers = drivingRoutes(fakeMk, trip, [drive(0)]);
    await settle();
    expect(await answers[0]).not.toBeNull();
    expect(fake.directions.calls).toHaveLength(1);
  });

  it("keeps the road when sending it to the server fails", async () => {
    server.mockImplementation(((_path: string, options?: { method?: string }) => options?.method === "PUT" ? Promise.reject(new Error("refused")) : Promise.resolve({ routes: [] })) as never);
    const answers = drivingRoutes(fakeMk, trip, [drive(0)]);
    await settle();
    expect(await answers[0]).not.toBeNull();
    expect(puts()).toHaveLength(1);
  });

  it("sends nothing when MapKit has no road either", async () => {
    fake.directions.mode = "error";
    const answers = drivingRoutes(fakeMk, trip, [drive(0)]);
    await settle();
    expect(await answers[0]).toBeNull();
    expect(puts()).toHaveLength(0);
  });

  it("asks the server about no more drives than it takes, and MapKit about the rest", async () => {
    const many = Array.from({ length: SERVER_MAX_DRIVES + 2 }, (_, n) => drive(n));
    drivingRoutes(fakeMk, trip, many);
    await settle();
    expect(String(gets()[0][0]).split("drive=")).toHaveLength(SERVER_MAX_DRIVES + 1);
  });

  it("drops what the server says once the cache has been cleared", async () => {
    let reply: (value: unknown) => void = () => {};
    server.mockImplementation((() => new Promise((resolve) => { reply = resolve; })) as never);
    const answers = drivingRoutes(fakeMk, trip, [drive(0)]);
    clearRouteCache();
    reply({ routes: [stored(0)] });
    await settle();
    expect(await answers[0]).toBeNull();
  });

  it("goes on to ask MapKit when the server lookup never settles", async () => {
    server.mockImplementation((() => new Promise(() => {})) as never);
    const answers = drivingRoutes(fakeMk, trip, [drive(0)]);
    await vi.advanceTimersByTimeAsync(LOOKUP_TIMEOUT_MS - 1);
    expect(fake.directions.calls).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(LOOKUP_TIMEOUT_MS);
    expect(await answers[0]).not.toBeNull();
    expect(fake.directions.calls).toHaveLength(1);
  });

  it("thins a path over the server's limit to the limit, keeping both ends", () => {
    const long = Array.from({ length: SERVER_MAX_POINTS * 3 + 1 }, (_, n) => [n, -n]);
    const short = thin(long);
    expect(short).toHaveLength(SERVER_MAX_POINTS);
    expect(short[0]).toEqual(long[0]);
    expect(short.at(-1)).toEqual(long.at(-1));
    expect(thin(long.slice(0, 5))).toHaveLength(5);
  });

  it("sends a thinned copy of a very long road", async () => {
    const long = Array.from({ length: SERVER_MAX_POINTS * 2 }, (_, n) => ({ latitude: 39.74 + n / 1e6, longitude: -104.99 }));
    const mk = { ...fakeMk, Directions: Object.assign(class { route(_r: unknown, done: (e: unknown, r: unknown) => void) { done(null, { routes: [{ path: long }] }); return 1; } }, { Transport: { Automobile: "automobile" } }) };
    const answer = drivingRoutes(mk as never, trip, [drive(0)])[0];
    await settle();
    await answer;
    expect((puts()[0][1] as { body: { path: unknown[] } }).body.path).toHaveLength(SERVER_MAX_POINTS);
  });
});

describe("the saved routes the Trips cards draw", () => {
  const pairs = road.map((c) => [c.latitude, c.longitude]);
  const entry = (trip: number, n: number, path = pairs) => ({ trip_id: trip, routes: [{ start: from, end: to(n), path }] });
  const wait = () => vi.advanceTimersByTimeAsync(CARD_WAIT_MS + 10);
  const asked = () => server.mock.calls.filter(([url]) => String(url).startsWith("/api/driving-routes"));
  const stop = (latitude: number, longitude: number, via: "flight" | null = null) => ({ name: "x", city: "x", code: null, kind: "stay" as const, latitude, longitude, from: "", to: "", via });

  it("asks once for every card that mounts together, and never asks MapKit", async () => {
    server.mockResolvedValue({ trips: [entry(1, 0), entry(3, 1)] });
    const answers = [1, 2, 3].map((t) => savedRoutes(t));
    await wait();
    const [one, two, three] = await Promise.all(answers);
    expect(asked()).toHaveLength(1);
    expect(asked()[0][0]).toBe("/api/driving-routes?trip=1&trip=2&trip=3");
    expect(one.size).toBe(1);
    expect(two.size).toBe(0);
    expect(three.size).toBe(1);
    expect(fake.directions.calls).toHaveLength(0);
    expect(puts()).toHaveLength(0);
  });

  function puts() { return server.mock.calls.filter(([, options]) => options?.method === "PUT"); }

  it("splits a long list into requests of the server's limit and asks for a trip only once", async () => {
    server.mockResolvedValue({ trips: [] });
    const ids = Array.from({ length: CARD_TRIPS * 2 + 1 }, (_, i) => i + 1);
    const answers = [...ids, ...ids].map((t) => savedRoutes(t));
    await wait();
    await Promise.all(answers);
    expect(asked()).toHaveLength(3);
    expect(asked().map(([url]) => String(url).split("&").length)).toEqual([CARD_TRIPS, CARD_TRIPS, 1]);
  });

  it("reads each route by its two places, thins a long path and ignores what it cannot read", async () => {
    const long = Array.from({ length: CARD_POINTS * 3 }, (_, i) => [40 + i / 10000, -108]);
    server.mockResolvedValue({ trips: [{ trip_id: 5, routes: [{ start: from, end: to(0), path: long }, { start: from, end: to(1), path: [[1, 2]] }, { start: "x", end: to(2), path: pairs }, { start: from, end: to(3), path: pairs }] }] });
    const answer = savedRoutes(5);
    await wait();
    const saved = await answer;
    expect([...saved.keys()]).toEqual(["39.7400,-104.9900>40.0000,-111.8900", "39.7400,-104.9900>40.3000,-111.8900"]);
    const path = saved.get("39.7400,-104.9900>40.0000,-111.8900")!;
    expect(path).toHaveLength(CARD_POINTS);
    expect([path[0], path.at(-1)]).toEqual([long[0], long.at(-1)]);
  });

  it("keeps a trip's answer for the next card, and asks again after a failure", async () => {
    server.mockRejectedValueOnce(new Error("down"));
    const failed = savedRoutes(1);
    await wait();
    expect((await failed).size).toBe(0);
    server.mockResolvedValue({ trips: [entry(1, 0)] });
    const again = savedRoutes(1);
    await wait();
    expect((await again).size).toBe(1);
    expect(await savedRoutes(1)).toBe(await again);
    expect(asked()).toHaveLength(2);
  });

  it("asks again for a trip once the replay has saved one of its routes", async () => {
    server.mockResolvedValue({ trips: [] });
    const first = savedRoutes(7);
    await wait();
    await first;
    const drawn = drivingRoutes(fakeMk, 7, [{ from, to: to(0) }])[0];
    await vi.advanceTimersByTimeAsync(300);
    await drawn;
    server.mockResolvedValue({ trips: [entry(7, 0)] });
    const next = savedRoutes(7);
    await wait();
    expect((await next).size).toBe(1);
  });

  it("answers nothing for a lookup that clearing the cache cut off, and keeps nothing of the old answer", async () => {
    server.mockResolvedValue({ trips: [entry(1, 0)] });
    const waiting = savedRoutes(1);
    clearRouteCache();
    expect((await waiting).size).toBe(0);
    await wait();
    expect(asked()).toHaveLength(0);
    let reply: (value: unknown) => void = () => {};
    server.mockReturnValueOnce(new Promise((resolve) => { reply = resolve; }) as never);
    const inFlight = savedRoutes(2);
    await wait();
    clearRouteCache();
    reply({ trips: [entry(2, 0)] });
    expect((await inFlight).size).toBe(0);
    const stale = savedRoutes(2);
    server.mockResolvedValue({ trips: [] });
    await wait();
    expect((await stale).size).toBe(0);
    server.mockResolvedValue({ trips: [entry(1, 0)] });
    const fresh = savedRoutes(1);
    await wait();
    expect((await fresh).size).toBe(1);
  });

  it("finds the saved path of each drive of a trip and none for a flight or a stop that stays put", () => {
    const saved = new Map([["39.7400,-104.9900>40.0000,-111.8900", pairs]]);
    const stops = [stop(39.74, -104.99), stop(40, -111.89), stop(40, -111.89), stop(51.47, -0.45, "flight")];
    const roads = savedRoads(stops, saved);
    expect(roads.legs).toHaveLength(1);
    expect(roads.legs[0].points).toBe(pairs);
    expect(roads.interstates).toEqual([]);
    expect(savedRoads([stop(39.74, -104.99), stop(40, -111.89, "flight")], saved).legs).toEqual([]);
    expect(savedRoads(stops, new Map()).legs).toEqual([]);
  });

  it("says whether a trip has a drive at all, so a flights-only trip is never looked up", () => {
    expect(hasDrive([stop(1, 2), stop(3, 4)])).toBe(true);
    expect(hasDrive([stop(1, 2), stop(3, 4, "flight")])).toBe(false);
    expect(hasDrive([stop(1, 2), stop(1, 2)])).toBe(false);
    expect(hasDrive([stop(1, 2)])).toBe(false);
  });
});
