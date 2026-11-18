// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fake, fakeMk, windingPath, type DirectionsMode, type FakeOverlay } from "../test/fake-mapkit";
import { apiCall } from "./contract";
import { clearRouteCache, ROUTE_TIMEOUT_MS } from "./driving-routes";
import { cutAt, createReplayMap, DEFAULT_PALETTE, legPath, mapPoint, mapRectFor, MAX_LATITUDE, mercatorFor, SAMPLES, WORLD, type ReplayMap, type ReplayMapOptions } from "./replay-mapkit";
import { geoMercator } from "d3-geo";
import { legsOf, positions, type Stop } from "./route-replay";

vi.mock("./contract", () => ({ apiCall: vi.fn() }));
const server = vi.mocked(apiCall);

const stopAt = (name: string, latitude: number, longitude: number, via: Stop["via"] = null, kind: Stop["kind"] = "airport"): Stop =>
  ({ name, city: name, code: kind === "airport" ? name.slice(0, 3).toUpperCase() : null, kind, latitude, longitude, from: "2025-12-05T08:00", to: "2025-12-05T10:00", via });
const flying = [stopAt("Minneapolis", 44.88, -93.22), stopAt("San Francisco", 37.62, -122.38, "flight"), stopAt("Minneapolis", 44.88, -93.22, "flight")];
const denver = stopAt("Denver", 39.74, -104.99, null, "stay"), saltLake = stopAt("Salt Lake City", 40.76, -111.89, null, "stay");
const options = (extra: Partial<ReplayMapOptions> = {}): ReplayMapOptions =>
  ({ stops: flying, width: 960, height: 520, palette: DEFAULT_PALETTE, scale: 1, onFailure: vi.fn(), ...extra });
const start = (extra: Partial<ReplayMapOptions> = {}): { replay: ReplayMap; opts: ReplayMapOptions } => {
  const opts = options(extra);
  return { replay: createReplayMap(fakeMk, document.createElement("div"), opts), opts };
};
const annotations = () => [...fake.last().annotations];
const moversOnMap = () => annotations().filter((a) => a.factory().hasAttribute("data-mover"));
const named = (name: string) => annotations().find((a) => a.factory().getAttribute("data-stop") === name)!;
const visibleStops = () => annotations().filter((a) => a.factory().hasAttribute("data-stop")).map((a) => a.factory().getAttribute("data-stop"));
const overlays = () => [...fake.last().overlays] as FakeOverlay[];
const colorOf = (o: FakeOverlay) => o.options.style!.options.strokeColor;

beforeEach(() => { fake.reset(); clearRouteCache(); server.mockReset(); server.mockResolvedValue({ routes: [] }); });

describe("the map's projection", () => {
  it("places the world's corners in MapKit's units", () => {
    expect(mapPoint(0, -180)).toEqual({ x: 0, y: WORLD / 2 });
    expect(mapPoint(0, 180).x).toBe(WORLD);
    expect(mapPoint(MAX_LATITUDE, 0).y).toBeLessThan(1e-5);
    expect(mapPoint(90, 0)).toEqual(mapPoint(MAX_LATITUDE, 0));
    expect(mapPoint(-90, 0).y).toBeGreaterThan(WORLD - 1e-5);
    expect(WORLD).toBe(1);
  });

  it("is a Mercator fit of the same stops the flat map shows", () => {
    const projection = mercatorFor(flying, 960, 520);
    const [x, y] = projection([-93.22, 44.88])!;
    expect(x).toBeGreaterThan(0);
    expect(y).toBeGreaterThan(0);
    const back = projection.invert!([x, y])!;
    expect(back[0]).toBeCloseTo(-93.22, 3);
    expect(back[1]).toBeCloseTo(44.88, 3);
  });
});

describe("the fake MapKit's rectangles", () => {
  it("refuse values outside 0 to 1, as MapKit JS's normalized units do", () => {
    expect(() => new fakeMk.MapRect(0.1, 0.2, 0.3, 0.3)).not.toThrow();
    expect(() => new fakeMk.MapRect(2 ** 27, 0, 100, 100)).toThrow(RangeError);
    expect(() => new fakeMk.MapRect(0.9, 0, 0.2, 0.1)).not.toThrow();
    expect(() => new fakeMk.MapRect(0, 0.95, 0.2, 0.1)).toThrow(/outside the world/);
    expect(() => new fakeMk.MapRect(-0.1, 0, 0.2, 0.1)).toThrow(RangeError);
    expect(() => new fakeMk.MapRect(1.2, 0, 0.2, 0.1)).toThrow(RangeError);
    expect(() => new fakeMk.MapRect(0.5, 0, 1.5, 0.1)).toThrow(RangeError);
  });

  it("see every camera move the replay makes inside the world", () => {
    const stops = [stopAt("Denver", 39.86, -104.67), stopAt("Salt Lake City", 40.79, -111.98, "flight"), stopAt("Park City", 40.65, -111.5, null, "stay")];
    const { replay } = start({ stops });
    for (const progress of [0, 0.2, 0.5, 0.8, 1]) replay.update({ progress, playing: true, calm: false });
    replay.update({ progress: 1, playing: false, calm: true });
    const rects = fake.last().rects;
    expect(rects.length).toBeGreaterThan(2);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.y).toBeGreaterThanOrEqual(0);
      expect(r.x + r.width).toBeLessThanOrEqual(1);
      expect(r.y + r.height).toBeLessThanOrEqual(1);
    }
  });
});

describe("the camera's rectangle across the date line", () => {
  const projection = geoMercator().scale(300).translate([480, 260]);

  it("is unchanged for a box that stays inside the world", () => {
    const r = mapRectFor(projection, { x: 480, y: 100, w: 200, h: 120 });
    expect(r.x).toBeCloseTo(0.5, 6);
    expect(r.width).toBeCloseTo(200 / (300 * 2 * Math.PI), 6);
    expect(r.x + r.width).toBeLessThan(1);
    expect(r.height).toBeGreaterThan(0);
    expect(r.y + r.height).toBeLessThanOrEqual(1);
  });

  it("keeps the short way round when the box crosses the date line, as a rect that wraps", () => {
    const r = mapRectFor(projection, { x: 1300, y: 100, w: 200, h: 120 });
    expect(r.x).toBeGreaterThan(0.9);
    expect(r.width).toBeCloseTo(200 / (300 * 2 * Math.PI), 6);
    expect(r.width).toBeLessThan(0.12);
    expect(r.x + r.width).toBeGreaterThan(1);
    expect(r.x + r.width).toBeLessThan(1.2);
  });

  it("covers the whole world, not more, for a box wider than it", () => {
    expect(mapRectFor(projection, { x: 0, y: 100, w: 3000, h: 100 }).width).toBe(1);
  });

  it("is what the replay hands MapKit for a route across the Pacific, with a camera that stays narrow", () => {
    const stops = [stopAt("Nadi", -17.76, 177.45), stopAt("Savusavu", -16.78, 179.34, null, "stay"), stopAt("Apia", -13.83, -171.75, "flight")];
    const { replay } = start({ stops });
    for (const progress of [0, 0.3, 0.6, 0.9, 1]) replay.update({ progress, playing: true, calm: false });
    for (const r of fake.last().rects) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.x).toBeLessThan(1);
      expect(r.width).toBeLessThanOrEqual(1);
      expect(r.x + r.width).toBeLessThanOrEqual(2);
      expect(r.width).toBeLessThan(0.15);
    }
    expect(fake.last().rects.some((r) => r.x + r.width > 1)).toBe(true);
  });
});

describe("cutting a path", () => {
  const path = { points: [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }], along: [0, 10, 20] };
  it("keeps the share of the length, ending between points", () => {
    expect(cutAt(path, 0)).toEqual([{ x: 0, y: 0 }, { x: 0, y: 0 }]);
    expect(cutAt(path, 0.25)).toEqual([{ x: 0, y: 0 }, { x: 5, y: 0 }]);
    expect(cutAt(path, 0.75)).toEqual([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 5 }]);
    expect(cutAt(path, 1)).toEqual(path.points);
    expect(cutAt(path, 7)).toEqual(path.points);
  });

  it("samples a flight's arc into a bowed line, a drive into a straight one, and uses a road's own points once it has one", () => {
    const projection = mercatorFor(flying, 960, 520);
    const [flight] = legsOf(flying, projection);
    const arc = legPath(flight);
    expect(arc.points).toHaveLength(SAMPLES + 1);
    expect(arc.points[0]).toEqual(flight.from);
    expect(arc.points.at(-1)).toEqual(flight.to);
    const middle = arc.points[SAMPLES / 2];
    const chord = { x: (flight.from.x + flight.to.x) / 2, y: (flight.from.y + flight.to.y) / 2 };
    expect(Math.hypot(middle.x - chord.x, middle.y - chord.y)).toBeGreaterThan(5);
    const driveProjection = mercatorFor([denver, saltLake], 960, 520);
    const [drive] = legsOf([denver, saltLake], driveProjection);
    const line = legPath(drive);
    expect(line.points).toHaveLength(SAMPLES + 1);
    for (const p of line.points) expect((p.x - drive.from.x) * (drive.to.y - drive.from.y) - (p.y - drive.from.y) * (drive.to.x - drive.from.x)).toBeCloseTo(0, 6);
    const road = { points: [drive.from, { x: drive.from.x + 5, y: drive.from.y - 9 }, drive.to], along: [0, 10, 20] };
    expect(legPath({ ...drive, road })).toBe(road);
    expect(positions([denver, saltLake], driveProjection)).toHaveLength(2);
  });
});

describe("the MapKit map", () => {
  it("is a dark, still map with none of MapKit's own controls", () => {
    start();
    const map = fake.last();
    expect(map.options).toMatchObject({ colorScheme: "dark", showsMapTypeControl: false, showsZoomControl: false, showsCompass: "hidden", showsScale: "hidden", isScrollEnabled: false, isZoomEnabled: false, isRotationEnabled: false });
  });

  it("starts with the first stop only, and frames the whole route", () => {
    const { replay } = start();
    replay.update({ progress: 0, playing: false, calm: false });
    expect(visibleStops()).toEqual(["Minneapolis"]);
    expect(overlays()).toHaveLength(0);
    const [rect] = fake.last().rects;
    expect(rect.x).toBeGreaterThan(0);
    expect(rect.x + rect.width).toBeLessThan(WORLD);
    expect(rect.width / rect.height).toBeCloseTo(960 / 520, 1);
  });

  it("adds each stop as it is reached, in the same glyph as the flat map", () => {
    const { replay } = start();
    replay.update({ progress: 0.5, playing: true, calm: false });
    expect(visibleStops()).toEqual(["Minneapolis", "San Francisco"]);
    replay.update({ progress: 1, playing: false, calm: false });
    expect(visibleStops()).toHaveLength(3);
    const glyph = (name: string, kind: string) => { const node = named(name).factory(); expect(node.getAttribute("data-kind")).toBe(kind); return node.querySelector("svg")!.innerHTML; };
    expect(glyph("Minneapolis", "airport")).toContain("fill-map-airport");
    const stay = start({ stops: [denver, saltLake] });
    stay.replay.update({ progress: 1, playing: false, calm: false });
    expect(named("Denver").factory().querySelector("rect")!.getAttribute("class")).toContain("fill-map-stay");
    const home = start({ stops: [{ ...denver, kind: "home" }, { ...saltLake, kind: "place" }] });
    home.replay.update({ progress: 1, playing: false, calm: false });
    expect(named("Denver").factory().querySelector("path[data-house]")).toBeTruthy();
    expect(named("Salt Lake City").factory().querySelector("circle:not([data-ping])")!.getAttribute("r")).toBe("4.5");
  });

  it("pulses the current stop only while playing", () => {
    const { replay } = start();
    const ping = () => named("San Francisco").factory().querySelector<SVGElement>("[data-ping]")!.style.display;
    replay.update({ progress: 0.5, playing: true, calm: false });
    expect(ping()).toBe("");
    replay.update({ progress: 0.5, playing: false, calm: false });
    expect(ping()).toBe("none");
    replay.update({ progress: 0.5, playing: true, calm: true });
    expect(ping()).toBe("none");
  });

  it("draws each leg in as time passes, in the flat map's colours and widths", () => {
    const { replay } = start({ palette: { route: "#111111", stay: "#222222" }, scale: 0.5 });
    replay.update({ progress: 0.25, playing: true, calm: false });
    const [first] = overlays();
    expect(overlays()).toHaveLength(1);
    expect(colorOf(first)).toBe("#111111");
    expect(first.options.style!.options).toMatchObject({ lineWidth: 1.25, lineCap: "round", lineJoin: "round" });
    const early = first.points.length;
    replay.update({ progress: 0.4, playing: true, calm: false });
    expect(overlays()[0]).toBe(first);
    expect(first.points.length).toBeGreaterThan(early);
    replay.update({ progress: 0.75, playing: true, calm: false });
    expect(overlays()).toHaveLength(2);
    const last = first.points.at(-1)!;
    expect(last.latitude).toBeCloseTo(37.62, 1);
    expect(last.longitude).toBeCloseTo(-122.38, 1);
    replay.update({ progress: 0.1, playing: false, calm: false });
    expect(overlays()).toHaveLength(1);
  });

  it("draws a drive with no Apple road yet as a straight line, in the ground colour", () => {
    const { replay } = start({ stops: [denver, saltLake], palette: { route: "#111111", stay: "#222222" } });
    replay.update({ progress: 1, playing: false, calm: false });
    const drive = overlays().find((o) => colorOf(o) === "#222222" && o.options.style!.options.lineWidth === 2)!;
    const [first, ...rest] = drive.points;
    const last = rest.at(-1)!;
    for (const p of rest) expect((p.longitude - first.longitude) * (last.latitude - first.latitude) - (p.latitude - first.latitude) * (last.longitude - first.longitude)).toBeCloseTo(0, 1);
  });

  it("moves a plane along its leg, hidden before and after, turned the way it flies", () => {
    const { replay } = start();
    const movers = moversOnMap;
    replay.update({ progress: 0, playing: false, calm: false });
    expect(movers()).toHaveLength(0);
    replay.update({ progress: 0.25, playing: true, calm: false });
    const [plane] = movers();
    expect(fake.last().annotations.has(plane)).toBe(true);
    expect(plane.factory().getAttribute("data-vehicle")).toBe("plane");
    expect(plane.factory().getAttribute("data-plane")).toBe("0");
    expect(plane.factory().querySelector("g")!.getAttribute("transform")).toMatch(/^rotate\(-?[\d.]+\) scale\(1\.1\)$/);
    const here = plane.coordinate;
    replay.update({ progress: 0.35, playing: true, calm: false });
    expect(plane.coordinate).not.toEqual(here);
    expect(plane.coordinate.longitude).toBeLessThan(here.longitude);
    replay.update({ progress: 0.5, playing: true, calm: false });
    expect(movers()).toHaveLength(0);
  });

  describe("the one mover", () => {
    const trip = [stopAt("Minneapolis", 44.88, -93.22), stopAt("Denver", 39.86, -104.67, "flight"), stopAt("Salt Lake City", 40.79, -111.98, "flight", "stay"), stopAt("Park City", 40.65, -111.5, null, "stay"), stopAt("Minneapolis", 44.88, -93.22, "flight")];
    const frame = (progress: number, calm = false) => ({ progress, playing: true, calm });
    const kinds = () => moversOnMap().map((a) => a.factory().getAttribute("data-vehicle"));

    it("is never more than one on the map as the replay passes leg after leg", () => {
      const { replay } = start({ stops: trip });
      const seen = new Set<string | null>();
      for (let progress = 0; progress <= 1.0001; progress += 0.01) {
        replay.update(frame(Math.min(1, progress)));
        expect(moversOnMap().length).toBeLessThanOrEqual(1);
        for (const v of kinds()) seen.add(v);
      }
      expect(seen.size).toBeGreaterThan(1);
    });

    it("is replaced, not left behind, when the next leg starts", () => {
      const { replay } = start({ stops: trip });
      replay.update(frame(0.1));
      const [first] = moversOnMap();
      expect(first.factory().getAttribute("data-mover")).toBe("0");
      replay.update(frame(0.4));
      expect(fake.last().annotations.has(first)).toBe(false);
      expect(moversOnMap()).toHaveLength(1);
      expect(moversOnMap()[0].factory().getAttribute("data-mover")).toBe("1");
    });

    it("is gone while paused at a stop, at the end, and when scrubbing back", () => {
      const { replay } = start({ stops: trip });
      replay.update(frame(0.1));
      expect(moversOnMap()).toHaveLength(1);
      replay.update({ progress: 0.5, playing: false, calm: false });
      expect(moversOnMap()).toHaveLength(0);
      replay.update(frame(0.62));
      expect(moversOnMap()).toHaveLength(1);
      replay.update({ progress: 1, playing: false, calm: false });
      expect(moversOnMap()).toHaveLength(0);
      replay.update(frame(0.6));
      expect(moversOnMap()).toHaveLength(1);
      replay.update({ progress: 0, playing: false, calm: false });
      expect(moversOnMap()).toHaveLength(0);
    });

    it("is not on the map at all in calm mode, even if it was moving a moment before", () => {
      const { replay } = start({ stops: trip });
      replay.update(frame(0.1));
      expect(moversOnMap()).toHaveLength(1);
      replay.update(frame(0.1, true));
      expect(moversOnMap()).toHaveLength(0);
      replay.update(frame(0.6, true));
      expect(moversOnMap()).toHaveLength(0);
    });

    it("is taken off the map when the replay is destroyed", () => {
      const { replay } = start({ stops: trip });
      replay.update(frame(0.1));
      replay.destroy();
      expect(fake.last().annotations.size).toBe(0);
    });
  });

  it("puts a stop on the map when it is reached and takes it off when scrubbed back before it", () => {
    const { replay } = start();
    replay.update({ progress: 1, playing: false, calm: false });
    expect(visibleStops()).toHaveLength(3);
    replay.update({ progress: 0.1, playing: false, calm: false });
    expect(visibleStops()).toEqual(["Minneapolis"]);
  });

  it("moves a car and a boat as the flat map does", () => {
    const car = start({ stops: [denver, saltLake] });
    car.replay.update({ progress: 0.5, playing: true, calm: false });
    expect(fake.last().annotations.size).toBe(2);
    expect(annotations().some((a) => a.factory().getAttribute("data-car") === "0")).toBe(true);
    const ship = start({ stops: [denver, { ...saltLake, via: "cruise" }] });
    ship.replay.update({ progress: 0.5, playing: true, calm: false });
    expect(annotations().some((a) => a.factory().getAttribute("data-boat") === "0")).toBe(true);
  });

  it("shows the whole route with every stop when the page asks for calm", () => {
    const { replay } = start();
    replay.update({ progress: 1, playing: false, calm: true });
    expect(visibleStops()).toEqual(["Minneapolis", "San Francisco", "Minneapolis"]);
    expect(overlays()).toHaveLength(2);
    expect(annotations().filter((a) => a.factory().hasAttribute("data-mover"))).toHaveLength(0);
    expect(fake.last().host.getAttribute("data-zoomed")).toBe("false");
  });

  it("zooms into a drive after a landing and back out", () => {
    const stops = [stopAt("Denver", 39.86, -104.67, null, "airport"), stopAt("Salt Lake City", 40.79, -111.98, "flight", "airport"), stopAt("Park City", 40.65, -111.5, null, "stay")];
    const { replay } = start({ stops });
    const host = fake.last().host;
    replay.update({ progress: 0, playing: false, calm: false });
    const wide = fake.last().rects.at(-1)!;
    replay.update({ progress: 0.8, playing: true, calm: false });
    const close = fake.last().rects.at(-1)!;
    expect(close.width).toBeLessThan(wide.width);
    expect(host.getAttribute("data-zoomed")).toBe("true");
    const count = fake.last().rects.length;
    replay.update({ progress: 0.8, playing: true, calm: false });
    expect(fake.last().rects).toHaveLength(count);
  });

  it("takes down what it put up, and stops listening, when it is destroyed", () => {
    const { replay } = start();
    replay.update({ progress: 0.9, playing: true, calm: false });
    expect(fake.listening("error")).toBe(1);
    replay.destroy();
    expect(fake.last().destroyed).toBe(true);
    expect(fake.last().annotations.size).toBe(0);
    expect(fake.listening("error")).toBe(0);
    replay.update({ progress: 1, playing: false, calm: false });
    replay.destroy();
  });

  it("reports an error MapKit raises later", () => {
    const { opts } = start();
    fake.emit("error", { status: "Unauthorized" });
    expect(opts.onFailure).toHaveBeenCalledTimes(1);
  });

  it("reports a failure while drawing instead of throwing", () => {
    const { replay, opts } = start();
    fake.broken = true;
    expect(() => replay.update({ progress: 0.5, playing: true, calm: false })).not.toThrow();
    expect(opts.onFailure).toHaveBeenCalled();
  });

  it("tears down a half-built map before it throws, leaving no listener behind", () => {
    fake.broken = true;
    expect(() => createReplayMap(fakeMk, document.createElement("div"), options())).toThrow("MapKit failed");
    expect(fake.last().destroyed).toBe(true);
    expect(fake.last().annotations.size).toBe(0);
    expect(fake.listening("error")).toBe(0);
  });

  it("keeps a throwing teardown from stopping the rest", () => {
    const { replay } = start();
    fake.last().destroy = () => { throw new Error("gone"); };
    expect(() => replay.destroy()).not.toThrow();
  });
});

describe("driving routes from Apple's directions", () => {
  afterEach(() => { vi.useRealTimers(); });
  const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 10));
  const calm = { progress: 1, playing: false, calm: true };
  const drive = [denver, saltLake];
  const origin = { latitude: denver.latitude, longitude: denver.longitude }, destination = { latitude: saltLake.latitude, longitude: saltLake.longitude };
  const legLine = () => overlays().find((o) => colorOf(o) === DEFAULT_PALETTE.stay)!;
  const here = (c: { latitude: number; longitude: number }) => ({ lat: c.latitude, lon: c.longitude });

  it("asks once for each drive leg, by car, and not again on every frame", async () => {
    const { replay } = start({ stops: [denver, saltLake, stopAt("Park City", 40.65, -111.5, null, "stay")] });
    for (const progress of [0, 0.2, 0.4, 0.6, 0.8, 1]) replay.update({ progress, playing: true, calm: false });
    await flush();
    for (const progress of [0.1, 0.5, 0.9, 1]) replay.update({ progress, playing: true, calm: false });
    await flush();
    expect(fake.directions.calls).toHaveLength(2);
    expect(fake.directions.calls.every((c) => c.transportType === "automobile")).toBe(true);
    expect(fake.directions.calls[0].origin).toMatchObject(origin);
    expect(fake.directions.calls[0].destination).toMatchObject(destination);
  });

  it("does not ask for flights, boats or trains", async () => {
    start({ stops: flying });
    start({ stops: [denver, { ...saltLake, via: "cruise" }] });
    start({ stops: [denver, { ...saltLake, via: "train" }] });
    await flush();
    expect(fake.directions.calls).toHaveLength(0);
  });

  it("asks for a drive that starts or ends at Home too", async () => {
    const home = stopAt("Home", 44.9, -93.1, null, "home");
    start({ stops: [home, denver] });
    start({ stops: [saltLake, stopAt("Home", 44.9, -93.1, null, "home")] });
    await flush();
    expect(fake.directions.calls).toHaveLength(2);
  });

  it("draws the line along the returned road, and keeps the car on it", async () => {
    const { replay } = start({ stops: drive });
    replay.update({ progress: 0.5, playing: true, calm: false });
    await flush();
    replay.update(calm);
    const road = windingPath(origin, destination).flat();
    const points = legLine().points;
    expect(points).toHaveLength(road.length + 2);
    road.forEach((c, i) => {
      expect(points[i + 1].latitude).toBeCloseTo(c.latitude, 4);
      expect(points[i + 1].longitude).toBeCloseTo(c.longitude, 4);
    });
  });

  it("redraws a leg already on screen when its road arrives, and moves the car onto it", async () => {
    const { replay } = start({ stops: drive });
    replay.update({ progress: 0.5, playing: true, calm: false });
    const line = legLine();
    const straight = line.points.length;
    await flush();
    expect(legLine()).toBe(line);
    expect(line.points.length).not.toBe(straight);
    const car = moversOnMap()[0];
    const tip = here(line.points.at(-1)!), at = here(car.coordinate);
    expect(at.lat).toBeCloseTo(tip.lat, 4);
    expect(at.lon).toBeCloseTo(tip.lon, 4);
    const road = windingPath(origin, destination).flat();
    expect(line.points.length).toBeLessThanOrEqual(road.length + 2);
  });

  it.each<DirectionsMode>(["error", "empty", "throw"])("keeps today's line, and raises no error, when the directions call goes wrong (%s)", async (mode) => {
    fake.directions.mode = mode;
    const { replay, opts } = start({ stops: drive });
    replay.update(calm);
    await flush();
    expect(legLine().points).toHaveLength(SAMPLES + 1);
    expect(opts.onFailure).not.toHaveBeenCalled();
  });

  it("gives up on a call that never answers after a few seconds, and keeps the line", async () => {
    vi.useFakeTimers();
    fake.directions.mode = "hang";
    const { replay, opts } = start({ stops: drive });
    replay.update(calm);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(ROUTE_TIMEOUT_MS - 1);
    expect(fake.directions.cancelled).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2);
    expect(fake.directions.cancelled).toHaveLength(1);
    expect(legLine().points).toHaveLength(SAMPLES + 1);
    expect(opts.onFailure).not.toHaveBeenCalled();
  });

  it("keeps the line when this MapKit has no directions at all", async () => {
    const old = { ...fakeMk, Directions: undefined };
    const opts = options({ stops: drive });
    const replay = createReplayMap(old, document.createElement("div"), opts);
    replay.update(calm);
    await flush();
    expect(legLine().points).toHaveLength(SAMPLES + 1);
    expect(opts.onFailure).not.toHaveBeenCalled();
  });

  it("asks Apple once for the same drive however often the replay is opened", async () => {
    start({ stops: drive });
    await flush();
    const again = start({ stops: drive });
    again.replay.update(calm);
    await flush();
    expect(fake.directions.calls).toHaveLength(1);
    expect(legLine().points).toHaveLength(windingPath(origin, destination).flat().length + 2);
  });

  it("asks again the next time after a failure", async () => {
    fake.directions.mode = "error";
    start({ stops: drive });
    await flush();
    fake.directions.mode = "ok";
    start({ stops: drive });
    await flush();
    expect(fake.directions.calls).toHaveLength(2);
  });

  it("ignores a road that arrives after the map is gone", async () => {
    const { replay } = start({ stops: drive });
    replay.update(calm);
    const line = legLine();
    const before = line.points.length;
    replay.destroy();
    await flush();
    expect(line.points).toHaveLength(before);
  });
});

describe("driving routes kept on the server", () => {
  const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 10));
  const calm = { progress: 1, playing: false, calm: true };
  const drive = [denver, saltLake];
  const legLine = () => overlays().find((o) => colorOf(o) === DEFAULT_PALETTE.stay)!;
  const origin = { latitude: denver.latitude, longitude: denver.longitude }, destination = { latitude: saltLake.latitude, longitude: saltLake.longitude };
  const road = () => windingPath(origin, destination).flat();
  const lookups = () => server.mock.calls.filter(([, o]) => o?.method !== "PUT");
  const stores = () => server.mock.calls.filter(([, o]) => o?.method === "PUT");

  it("asks MapKit on a first replay and stores each path, and a reload of the same trip asks MapKit for none", async () => {
    start({ stops: [denver, saltLake, stopAt("Park City", 40.65, -111.5, null, "stay")], tripId: 12 });
    await flush();
    expect(fake.directions.calls).toHaveLength(2);
    expect(stores().map(([path]) => path)).toEqual(["/api/trips/12/driving-routes", "/api/trips/12/driving-routes"]);
    const kept = stores().map(([, o]) => (o as { body: { start: unknown; end: unknown; path: number[][] } }).body);

    clearRouteCache();
    fake.reset();
    server.mockReset();
    server.mockResolvedValue({ routes: kept } as never);
    const { replay } = start({ stops: [denver, saltLake, stopAt("Park City", 40.65, -111.5, null, "stay")], tripId: 12 });
    replay.update(calm);
    await flush();
    expect(fake.directions.calls).toHaveLength(0);
    expect(lookups()).toHaveLength(1);
    expect(stores()).toHaveLength(0);
    expect(legLine().points).toHaveLength(road().length + 2);
  });

  it("gets a second device's paths from the server in one request and asks MapKit for none", async () => {
    server.mockResolvedValue({ routes: [{ start: origin, end: destination, path: road().map((c) => [c.latitude, c.longitude]) }] });
    const { replay } = start({ stops: drive, tripId: 3 });
    replay.update(calm);
    await flush();
    expect(fake.directions.calls).toHaveLength(0);
    expect(lookups()).toHaveLength(1);
    expect(lookups()[0][0]).toBe("/api/trips/3/driving-routes?drive=39.7400,-104.9900,40.7600,-111.8900");
    expect(legLine().points).toHaveLength(road().length + 2);
  });

  it("keeps today's behaviour when the server fails or has nothing: MapKit is asked, and the line is still drawn", async () => {
    for (const reply of [() => Promise.reject(new Error("down")), () => Promise.resolve({ routes: [] }), () => Promise.resolve(undefined)]) {
      clearRouteCache();
      fake.reset();
      server.mockReset();
      server.mockImplementation(reply as never);
      const { replay, opts } = start({ stops: drive, tripId: 3 });
      replay.update(calm);
      await flush();
      expect(fake.directions.calls).toHaveLength(1);
      expect(legLine().points).toHaveLength(road().length + 2);
      expect(opts.onFailure).not.toHaveBeenCalled();
    }
  });

  it("draws a straight line for a drive that neither the server nor MapKit has a path for", async () => {
    fake.directions.mode = "empty";
    const { replay } = start({ stops: drive, tripId: 3 });
    replay.update(calm);
    await flush();
    expect(legLine().points).toHaveLength(SAMPLES + 1);
    expect(stores()).toHaveLength(0);
  });

  it("does not touch the server without a trip", async () => {
    start({ stops: drive });
    await flush();
    expect(server).not.toHaveBeenCalled();
    expect(fake.directions.calls).toHaveLength(1);
  });

  it("sends no request for a replay with no drives", async () => {
    start({ stops: flying, tripId: 3 });
    await flush();
    expect(server).not.toHaveBeenCalled();
  });
});
