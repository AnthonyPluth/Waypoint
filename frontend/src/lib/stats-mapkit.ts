import type { StatsFlights, StatsMapTrip, StatsPlacePoint, StatsStayPin, StatsVisit } from "./api-types";
import {
  arcs, countrySources, dots, flownBounds, greatCircle, pins, stateSources, toOverlays, US_ID, visitedFeatureIds, visitedPoints, visitedStateTrips,
  type Bounds, type Country, type LonLat,
} from "./map";
import type { Mk, MkAnnotation, MkEvent, MkMap, MkOverlay } from "./mapkit";
import { mapPoint } from "./replay-mapkit";

export type StatsMapData = { flights: StatsFlights; stays: StatsStayPin[]; visits: StatsVisit[]; points: StatsPlacePoint[] };
export type Pick = { label: string; trips: StatsMapTrip[] };
export type Palette = { visited: string; route: string; airport: string; stay: string; sea: string };
export type StatsMapOptions = {
  palette: Palette;
  countries: Country[] | null;
  loadStates: () => Promise<Country[]>;
  contains: (feature: Country, lonLat: LonLat) => boolean;
  phone: boolean;
  onpick: (pick: Pick | null) => void;
  onfailure: () => void;
};
export type Described = { label: string; kind: "airport" | "route" | "stay" | "country" | "state" };
export type StatsMap = { show(data: StatsMapData): void; describe(drawn: object): Described | null; destroy(): void };

export const DEFAULT_PALETTE: Palette = { visited: "#3d7bc7", route: "#8fc2ff", airport: "#f6b73c", stay: "#4fd1b0", sea: "#0b0e15" };
export const STATES_BELOW_DEGREES = 40;
export const FRAME_PADDING = 0.15;
export const MIN_SPAN_DEGREES = 1.2;
export const FILL_OPACITY = 0.35;
export const EDGE_OPACITY = 0.7;

const SVG = "http://www.w3.org/2000/svg";
const lat = (y: number) => Math.max(-85, Math.min(85, y));

export function frameOf(bounds: Bounds | null): { x: number; y: number; width: number; height: number } {
  if (!bounds) return { x: 0, y: 0, width: 1, height: 1 };
  const span = bounds.east >= bounds.west ? bounds.east - bounds.west : bounds.east + 360 - bounds.west;
  const wide = Math.min(360, Math.max(span, MIN_SPAN_DEGREES) * (1 + 2 * FRAME_PADDING));
  const middle = bounds.west + span / 2;
  const west = middle - wide / 2;
  const top = mapPoint(lat(bounds.north), 0).y;
  const bottom = mapPoint(lat(bounds.south), 0).y;
  const grow = Math.max(MIN_SPAN_DEGREES / 360 - (bottom - top), 0) / 2 + (bottom - top) * FRAME_PADDING;
  const y = Math.max(0, top - grow);
  return { x: ((((west + 180) / 360) % 1) + 1) % 1, y, width: wide / 360, height: Math.min(1, bottom + grow) - y };
}

export function unwrapped(points: LonLat[]): LonLat[] {
  const out: LonLat[] = [];
  let shift = 0;
  for (const [lon, la] of points) {
    const last = out[out.length - 1];
    if (last) {
      const raw = lon + shift;
      if (raw - last[0] > 180) shift -= 360;
      else if (last[0] - raw > 180) shift += 360;
    }
    out.push([lon + shift, la]);
  }
  return out;
}

function glyph(content: SVGElement, radius: number): HTMLElement {
  const host = document.createElement("div");
  host.style.cssText = "position:relative;width:0;height:0";
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `${-radius} ${-radius} ${radius * 2} ${radius * 2}`);
  svg.setAttribute("width", String(radius * 2));
  svg.setAttribute("height", String(radius * 2));
  svg.setAttribute("aria-hidden", "true");
  svg.style.cssText = `position:absolute;left:${-radius}px;top:${-radius}px;overflow:visible`;
  svg.append(content);
  host.append(svg);
  return host;
}

function shape<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number>): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attributes)) node.setAttribute(k, String(v));
  return node;
}

type Item = { pick: Pick; kind: "airport" | "route" | "stay" | "country" | "state"; mark?: SVGElement };
type Placed = { overlay: MkOverlay; id: string | number };

export function createStatsMap(mk: Mk, host: HTMLElement, options: StatsMapOptions): StatsMap {
  const { palette, countries, contains, onpick, onfailure } = options;
  let map: MkMap | null = new mk.Map(host, {
    colorScheme: mk.Map.ColorSchemes.Dark, showsMapTypeControl: false, showsZoomControl: true, showsCompass: mk.FeatureVisibility.Hidden,
    showsScale: mk.FeatureVisibility.Hidden, showsPointsOfInterest: false, isRotationEnabled: false, isScrollEnabled: !options.phone,
  });
  let over = false;
  let framed: number | null = null;
  let spanNow = 360;
  let data: StatsMapData | null = null;
  let countryLayer: Placed[] = [];
  let stateLayer: Placed[] = [];
  let lines: MkOverlay[] = [];
  let marks: MkAnnotation[] = [];
  let shown = new Set<MkOverlay>();
  let states: Country[] | null = null;
  let asked = 0;
  let selected: Item | null = null;
  let items = new WeakMap<object, Item>();

  const fail = () => { if (!over) onfailure(); };
  const guard = <T>(work: () => T): T | undefined => {
    try { return work(); } catch { fail(); return undefined; }
  };
  const coordinate = ([lon, la]: LonLat) => new mk.Coordinate(lat(la), lon);
  const polygon = (feature: Country, pick: Pick, kind: Item["kind"]): MkOverlay | null => {
    const rings = toOverlays(feature);
    if (rings.length === 0) return null;
    const overlay = new mk.PolygonOverlay(rings.map((ring) => ring.map(coordinate)), { style: regionStyle(false), enabled: true });
    items.set(overlay, { pick, kind });
    return overlay;
  };
  const regionStyle = (on: boolean) => new mk.Style({
    fillColor: palette.visited, fillOpacity: FILL_OPACITY, strokeColor: on ? "#ffffff" : palette.visited, strokeOpacity: on ? 1 : EDGE_OPACITY, lineWidth: on ? 2 : 1,
  });

  const mark = (item: Item, on: boolean) => {
    if (item.mark) item.mark.setAttribute("stroke", on ? "#ffffff" : palette.sea);
  };
  const choose = (next: Item | null) => {
    if (selected && selected !== next) {
      mark(selected, false);
      const old = [...countryLayer, ...stateLayer].find((p) => items.get(p.overlay) === selected);
      if (old) guard(() => { old.overlay.style = regionStyle(false); });
    }
    selected = next;
    if (next) {
      mark(next, true);
      const now = [...countryLayer, ...stateLayer].find((p) => items.get(p.overlay) === next);
      if (now) guard(() => { now.overlay.style = regionStyle(true); });
    }
    onpick(next ? next.pick : null);
  };
  const itemOf = (event: MkEvent): Item | null => { const drawn = event.annotation ?? event.overlay; return drawn ? items.get(drawn) ?? null : null; };
  const picked = (event: MkEvent) => { if (!over) choose(itemOf(event)); };
  const dropped = () => { if (!over) choose(null); };

  const layers = () => {
    if (!map || over) return;
    const byState = spanNow < STATES_BELOW_DEGREES && states !== null;
    const wanted = new Set<MkOverlay>([
      ...countryLayer.filter((p) => !(byState && p.id === US_ID)).map((p) => p.overlay),
      ...(byState ? stateLayer.map((p) => p.overlay) : []),
    ]);
    const stale = [...shown].filter((overlay) => !lines.includes(overlay) && !wanted.has(overlay));
    const fresh = [...wanted].filter((overlay) => !shown.has(overlay));
    const missing = lines.some((line) => !shown.has(line));
    if (stale.length === 0 && fresh.length === 0 && !missing) return;
    for (const line of lines) if (shown.has(line)) { map.removeOverlay(line); shown.delete(line); }
    for (const overlay of stale) { map.removeOverlay(overlay); shown.delete(overlay); }
    for (const overlay of fresh) { map.addOverlay(overlay); shown.add(overlay); }
    for (const line of lines) { map.addOverlay(line); shown.add(line); }
  };

  const buildStates = () => {
    if (!data || !states) { stateLayer = []; return; }
    const trips = visitedStateTrips(stateSources(data.flights, data.stays, data.points, data.visits), states, contains);
    stateLayer = [];
    for (const feature of states) {
      const id = feature.id ?? "";
      const found = trips.get(id);
      if (!found) continue;
      const overlay = polygon(feature, { label: feature.properties?.name ?? "", trips: found }, "state");
      if (overlay) stateLayer.push({ overlay, id });
    }
  };

  const wantStates = () => {
    if (states !== null || asked > 0 || !data || spanNow >= STATES_BELOW_DEGREES) return;
    const mine = ++asked;
    options.loadStates().then((found) => {
      if (over || mine !== asked) return;
      states = found;
      guard(() => { buildStates(); layers(); });
    }, () => { states = null; });
  };

  const ended = () => {
    const delta = map?.region?.span.longitudeDelta;
    if (delta === undefined || over) return;
    spanNow = delta;
    if (framed === null) framed = delta;
    else if (options.phone && map && delta < framed * 0.9) map.isScrollEnabled = true;
    guard(() => { layers(); wantStates(); });
  };

  map.addEventListener?.("select", picked);
  map.addEventListener?.("deselect", dropped);
  map.addEventListener?.("region-change-end", ended);
  const watch = () => fail();
  mk.addEventListener("error", watch);

  const clear = () => {
    if (!map) return;
    for (const overlay of shown) { try { map.removeOverlay(overlay); } catch { continue; } }
    shown = new Set();
    for (const a of marks) { try { map.removeAnnotation(a); } catch { continue; } }
    marks = []; lines = []; countryLayer = []; stateLayer = []; items = new WeakMap();
  };

  const draw = () => {
    if (!map || !data) return;
    const { flights, stays, visits, points } = data;
    const flown = arcs(flights.routes);
    const airports = dots(flights.airports);
    const stayPins = pins(stays);
    const visited = countries ? visitedFeatureIds(visitedPoints(flights.airports, stays, visits), countries, contains) : new Set<string | number>();
    const byCountry = countries ? visitedStateTrips(countrySources(flights, stays, visits), countries, contains) : new Map<string | number, StatsMapTrip[]>();
    countryLayer = [];
    for (const feature of countries ?? []) {
      const id = feature.id ?? "";
      if (!visited.has(id)) continue;
      const overlay = polygon(feature, { label: feature.properties?.name ?? "", trips: byCountry.get(id) ?? [] }, "country");
      if (overlay) countryLayer.push({ overlay, id });
    }
    buildStates();
    lines = flown.map((a) => {
      const line = new mk.PolylineOverlay(unwrapped(greatCircle(a.from, a.to)).map(coordinate), {
        style: new mk.Style({ strokeColor: palette.route, strokeOpacity: 0.85, lineWidth: a.width, lineCap: "round", lineJoin: "round" }), enabled: true,
      });
      items.set(line, { pick: { label: a.label, trips: a.trips }, kind: "route" });
      return line;
    });
    layers();
    for (const s of stayPins) {
      const diamond = shape("rect", { x: -4, y: -4, width: 8, height: 8, transform: "rotate(45)", fill: palette.stay, stroke: palette.sea, "stroke-width": 1.5, "data-mark": "stay" });
      const pin = new mk.Annotation(coordinate([s.longitude, s.latitude]), () => glyph(diamond, 12));
      items.set(pin, { pick: { label: s.label, trips: s.trips }, kind: "stay", mark: diamond });
      marks.push(pin);
    }
    for (const d of airports) {
      const circle = shape("circle", { r: d.r, fill: palette.airport, stroke: palette.sea, "stroke-width": 1.5, "data-mark": "airport" });
      const dot = new mk.Annotation(coordinate([d.longitude, d.latitude]), () => glyph(circle, Math.max(d.r, 9) + 2));
      items.set(dot, { pick: { label: d.label, trips: [] }, kind: "airport", mark: circle });
      marks.push(dot);
    }
    for (const a of marks) map.addAnnotation(a);
    framed = null;
    const rect = frameOf(flownBounds(flights, stays, [...points, ...visits.filter((v) => v.state)]));
    map.setVisibleMapRectAnimated(new mk.MapRect(rect.x, rect.y, rect.width, rect.height), false);
  };

  return {
    show(next) {
      if (over || !map) return;
      data = next;
      selected = null;
      onpick(null);
      guard(() => { clear(); draw(); });
    },
    describe(drawn) {
      const item = items.get(drawn);
      return item ? { label: item.pick.label, kind: item.kind } : null;
    },
    destroy() {
      over = true;
      mk.removeEventListener("error", watch);
      map?.removeEventListener?.("select", picked);
      map?.removeEventListener?.("deselect", dropped);
      map?.removeEventListener?.("region-change-end", ended);
      try { map?.destroy(); } catch { map = null; }
    },
  };
}
