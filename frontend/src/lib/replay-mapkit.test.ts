// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fake, fakeMk, type FakeOverlay } from "../test/fake-mapkit";
import { cutAt, createReplayMap, DEFAULT_PALETTE, legPath, mapPoint, mapRectFor, MAX_LATITUDE, mercatorFor, SAMPLES, WORLD, type ReplayMap, type ReplayMapOptions } from "./replay-mapkit";
import { geoMercator } from "d3-geo";
import { legsOf, positions, type Roads, type Stop } from "./route-replay";

const stopAt = (name: string, latitude: number, longitude: number, via: Stop["via"] = null, kind: Stop["kind"] = "airport"): Stop =>
  ({ name, city: name, code: kind === "airport" ? name.slice(0, 3).toUpperCase() : null, kind, latitude, longitude, from: "2025-12-05T08:00", to: "2025-12-05T10:00", via });
const flying = [stopAt("Minneapolis", 44.88, -93.22), stopAt("San Francisco", 37.62, -122.38, "flight"), stopAt("Minneapolis", 44.88, -93.22, "flight")];
const none: Roads = { legs: [], interstates: [] };
const denver = stopAt("Denver", 39.74, -104.99, null, "stay"), saltLake = stopAt("Salt Lake City", 40.76, -111.89, null, "stay");
const roads: Roads = {
  legs: [{ from_segment_id: 1, to_segment_id: 2, refs: ["I-25", "I-80"], points: [[39.77, -105.0], [40.2, -105.0], [41.2, -107.5], [40.75, -111.85]] }],
  interstates: [{ ref: "I-25", points: [[39.0, -105.0], [40.2, -105.0]] }, { ref: "I-80", points: [[41.2, -107.5], [40.75, -111.85]] }],
};
const boundaries = [{ points: [[40.99, -109.05], [37.0, -109.05]] }];

const options = (extra: Partial<ReplayMapOptions> = {}): ReplayMapOptions =>
  ({ stops: flying, roads: none, boundaries: [], width: 960, height: 520, palette: DEFAULT_PALETTE, scale: 1, onFailure: vi.fn(), ...extra });
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

beforeEach(() => fake.reset());

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
    const projection = mercatorFor(flying, 960, 520, none);
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
    }
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

  it("samples a flight's arc into a bowed line and uses a road's own points", () => {
    const projection = mercatorFor(flying, 960, 520, none);
    const [flight] = legsOf(flying, projection, none);
    const arc = legPath(flight);
    expect(arc.points).toHaveLength(SAMPLES + 1);
    expect(arc.points[0]).toEqual(flight.from);
    expect(arc.points.at(-1)).toEqual(flight.to);
    const middle = arc.points[SAMPLES / 2];
    const chord = { x: (flight.from.x + flight.to.x) / 2, y: (flight.from.y + flight.to.y) / 2 };
    expect(Math.hypot(middle.x - chord.x, middle.y - chord.y)).toBeGreaterThan(5);
    const roadProjection = mercatorFor([denver, saltLake], 960, 520, roads);
    const [drive] = legsOf([denver, saltLake], roadProjection, roads);
    expect(legPath(drive)).toBe(drive.road);
    expect(positions([denver, saltLake], roadProjection)).toHaveLength(2);
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
    const stay = start({ stops: [denver, saltLake], roads });
    stay.replay.update({ progress: 1, playing: false, calm: false });
    expect(named("Denver").factory().querySelector("rect")!.getAttribute("class")).toContain("fill-map-stay");
    const home = start({ stops: [{ ...denver, kind: "home" }, { ...saltLake, kind: "place" }], roads });
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
    const { replay } = start({ palette: { route: "#111111", stay: "#222222", border: "#333333" }, scale: 0.5 });
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

  it("draws a drive along its road, in the ground colour", () => {
    const { replay } = start({ stops: [denver, saltLake], roads, palette: { route: "#111111", stay: "#222222", border: "#333333" } });
    replay.update({ progress: 1, playing: false, calm: false });
    const drive = overlays().find((o) => colorOf(o) === "#222222" && o.options.style!.options.lineWidth === 2)!;
    expect(drive.points.length).toBeGreaterThanOrEqual(4);
    expect(drive.points[1].latitude).toBeCloseTo(39.77, 1);
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
      const { replay } = start({ stops: trip, roads: none });
      const seen = new Set<string | null>();
      for (let progress = 0; progress <= 1.0001; progress += 0.01) {
        replay.update(frame(Math.min(1, progress)));
        expect(moversOnMap().length).toBeLessThanOrEqual(1);
        for (const v of kinds()) seen.add(v);
      }
      expect(seen.size).toBeGreaterThan(1);
    });

    it("is replaced, not left behind, when the next leg starts", () => {
      const { replay } = start({ stops: trip, roads: none });
      replay.update(frame(0.1));
      const [first] = moversOnMap();
      expect(first.factory().getAttribute("data-mover")).toBe("0");
      replay.update(frame(0.4));
      expect(fake.last().annotations.has(first)).toBe(false);
      expect(moversOnMap()).toHaveLength(1);
      expect(moversOnMap()[0].factory().getAttribute("data-mover")).toBe("1");
    });

    it("is gone while paused at a stop, at the end, and when scrubbing back", () => {
      const { replay } = start({ stops: trip, roads: none });
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
      const { replay } = start({ stops: trip, roads: none });
      replay.update(frame(0.1));
      expect(moversOnMap()).toHaveLength(1);
      replay.update(frame(0.1, true));
      expect(moversOnMap()).toHaveLength(0);
      replay.update(frame(0.6, true));
      expect(moversOnMap()).toHaveLength(0);
    });

    it("is taken off the map when the replay is destroyed", () => {
      const { replay } = start({ stops: trip, roads: none });
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
    const car = start({ stops: [denver, saltLake], roads });
    car.replay.update({ progress: 0.5, playing: true, calm: false });
    expect(fake.last().annotations.size).toBeGreaterThan(2);
    expect(annotations().some((a) => a.factory().getAttribute("data-car") === "0")).toBe(true);
    const ship = start({ stops: [denver, { ...saltLake, via: "cruise" }], roads: none });
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

  it("draws the highways and state lines the flat map draws, with shields, only where they are in view", () => {
    const { replay } = start({ stops: [denver, saltLake], roads, boundaries });
    replay.update({ progress: 1, playing: false, calm: true });
    const widths = overlays().map((o) => o.options.style!.options.lineWidth);
    expect(widths.filter((w) => w === 1.6)).toHaveLength(2);
    const dashed = overlays().filter((o) => o.options.style!.options.lineDash);
    expect(dashed).toHaveLength(1);
    expect(dashed[0].options.style!.options).toMatchObject({ lineDash: [4, 3], strokeOpacity: 0.8, lineWidth: 1 });
    const shields = annotations().filter((a) => a.factory().hasAttribute("data-shield"));
    expect(shields.map((s) => s.factory().getAttribute("data-shield")).sort()).toEqual(["I-25", "I-80"]);
    expect(shields[0].factory().textContent).toMatch(/^I-/);
    replay.update({ progress: 1, playing: false, calm: true });
    expect(annotations().filter((a) => a.factory().hasAttribute("data-shield"))).toHaveLength(2);
  });

  it("leaves the highways and state lines out when there are none", () => {
    const { replay } = start({ stops: [denver, saltLake], roads: none });
    replay.update({ progress: 1, playing: false, calm: true });
    expect(overlays().every((o) => o.options.style!.options.lineWidth !== 1.6)).toBe(true);
    expect(annotations().some((a) => a.factory().hasAttribute("data-shield"))).toBe(false);
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
