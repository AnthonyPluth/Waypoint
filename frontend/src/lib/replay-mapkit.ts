import { geoBounds, geoMercator, type GeoProjection } from "d3-geo";
import { drivingRoutes, type Drive } from "./driving-routes";
import type { Mk, MkAnnotation, MkMap, MkOverlay } from "./mapkit";
import {
  activeStop, cameraAt, legProgress, legsOf, moverAt, positions, reached, routeProjection,
  type Box, type Leg, type Roads, type Spot, type Stop, type Vehicle,
} from "./route-replay";

export type Frame = { progress: number; playing: boolean; calm: boolean };
export type Palette = { route: string; stay: string; border: string };
export type ReplayMapOptions = { stops: Stop[]; roads: Roads; width: number; height: number; palette: Palette; scale: number; onFailure: () => void; tripId?: number; more?: Pick<Stop, "latitude" | "longitude">[]; onView?: (box: Box) => void };
export type ReplayMap = { update(frame: Frame): void; destroy(): void };

export const WORLD = 1;
export const MAX_LATITUDE = 85.0511;
export const SAMPLES = 64;
export const FLIGHT_WIDTH = 2.5;
export const GROUND_WIDTH = 2;
export const MOVER_SCALE = 1.1;
export const DEFAULT_PALETTE: Palette = { route: "#8fc2ff", stay: "#4fd1b0", border: "#343c52" };

const SVG = "http://www.w3.org/2000/svg";
const lat = (y: number) => Math.max(-MAX_LATITUDE, Math.min(MAX_LATITUDE, y));

export const mapPoint = (latitude: number, longitude: number): Spot => ({
  x: ((longitude + 180) / 360) * WORLD,
  y: (0.5 - Math.log(Math.tan(Math.PI / 4 + (lat(latitude) * Math.PI) / 360)) / (2 * Math.PI)) * WORLD,
});

export function mapRectFor(projection: GeoProjection, box: Box): { x: number; y: number; width: number; height: number } {
  const top = projection.invert?.([box.x, box.y]) ?? [0, 0];
  const bottom = projection.invert?.([box.x, box.y + box.h]) ?? [0, 0];
  const a = mapPoint(top[1], top[0]), b = mapPoint(bottom[1], bottom[0]);
  const x = (((top[0] + 180) / 360) % 1 + 1) % 1;
  return { x, y: Math.min(a.y, b.y), width: Math.min(1, box.w / (projection.scale() * 2 * Math.PI)), height: Math.abs(b.y - a.y) };
}

function centreLongitude(stops: Stop[]): number {
  if (stops.length === 0) return 0;
  const [[west], [east]] = geoBounds({ type: "MultiPoint", coordinates: stops.map((s) => [s.longitude, s.latitude]) });
  const span = ((east - west) % 360 + 360) % 360;
  return west + span / 2;
}

export const mercatorFor = (stops: Stop[], width: number, height: number, roads: Roads, more: Pick<Stop, "latitude" | "longitude">[] = []): GeoProjection => {
  const centre = centreLongitude(stops);
  return routeProjection(stops, width, height, undefined, roads, () => geoMercator().rotate([-centre, 0]), more);
};

type Path = { points: Spot[]; along: number[] };

function pathOf(points: Spot[]): Path {
  const along = [0];
  for (let i = 1; i < points.length; i++) along.push(along[i - 1] + Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y));
  return { points, along };
}

export function legPath(leg: Leg): Path {
  if (leg.road) return leg.road;
  const points: Spot[] = [];
  for (let i = 0; i <= SAMPLES; i++) {
    const t = i / SAMPLES;
    const u = 1 - t;
    points.push({ x: u * u * leg.from.x + 2 * u * t * leg.control.x + t * t * leg.to.x, y: u * u * leg.from.y + 2 * u * t * leg.control.y + t * t * leg.to.y });
  }
  return pathOf(points);
}

export function cutAt(path: Path, share: number): Spot[] {
  const total = path.along[path.along.length - 1];
  const target = total * Math.min(1, Math.max(0, share));
  const out: Spot[] = [path.points[0]];
  for (let k = 1; k < path.points.length; k++) {
    if (path.along[k] <= target) { out.push(path.points[k]); continue; }
    const span = path.along[k] - path.along[k - 1];
    const u = span === 0 ? 0 : (target - path.along[k - 1]) / span;
    out.push({ x: path.points[k - 1].x + (path.points[k].x - path.points[k - 1].x) * u, y: path.points[k - 1].y + (path.points[k].y - path.points[k - 1].y) * u });
    break;
  }
  return out;
}

function element<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number>, ...children: SVGElement[]): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attributes)) node.setAttribute(k, String(v));
  node.append(...children);
  return node;
}

function anchored(content: SVGElement, radius: number, attributes: Record<string, string>): HTMLElement {
  const host = document.createElement("div");
  host.style.cssText = "position:relative;width:0;height:0;pointer-events:none";
  for (const [k, v] of Object.entries(attributes)) host.setAttribute(k, v);
  const svg = element("svg", { viewBox: `${-radius} ${-radius} ${radius * 2} ${radius * 2}`, width: radius * 2, height: radius * 2, "aria-hidden": "true" }, content);
  svg.style.cssText = `position:absolute;left:${-radius}px;top:${-radius}px;overflow:visible`;
  host.append(svg);
  return host;
}

function stopGlyph(stop: Stop): SVGElement {
  if (stop.kind === "stay") return element("rect", { x: -6, y: -6, width: 12, height: 12, rx: 2, transform: "rotate(45)", class: "fill-map-stay stroke-map-sea", "stroke-width": 2 });
  if (stop.kind === "home") return element("path", { d: "M0 -8 L8 -1 L5.5 -1 L5.5 6 L-5.5 6 L-5.5 -1 L-8 -1 Z", class: "fill-map-visited stroke-map-sea", "stroke-width": 2, "stroke-linejoin": "round", "data-house": "" });
  if (stop.kind === "airport") return element("circle", { r: 6, class: "fill-map-airport stroke-map-sea", "stroke-width": 2 });
  return element("circle", { r: 4.5, class: "fill-map-visited stroke-map-sea", "stroke-width": 2 });
}

function stopElement(stop: Stop): { node: HTMLElement; ping: SVGElement } {
  const ping = element("circle", { r: 10, class: "animate-ping fill-map-airport/60", style: "transform-box: fill-box; transform-origin: center", "data-ping": "" });
  ping.style.display = "none";
  return { node: anchored(element("g", {}, ping, stopGlyph(stop)), 12, { "data-stop": stop.name, "data-kind": stop.kind }), ping };
}

function moverGlyph(vehicle: Vehicle): SVGElement {
  if (vehicle === "plane") return element("path", { d: "M12 0 L3 -2.5 L-2 -10 L-5 -10 L-3 -1.5 L-8 -1.5 L-10 -4 L-12.5 -4 L-10.5 0 L-12.5 4 L-10 4 L-8 1.5 L-3 1.5 L-5 10 L-2 10 L3 2.5 Z", class: "fill-map-route stroke-map-sea", "stroke-width": 1.2, "stroke-linejoin": "round" });
  if (vehicle === "car") return element("g", {}, element("rect", { x: -9, y: -5, width: 18, height: 10, rx: 3, class: "fill-map-stay stroke-map-sea", "stroke-width": 1.2 }), element("rect", { x: 1, y: -3.5, width: 4, height: 7, rx: 1, class: "fill-map-sea" }));
  return element("path", { d: "M12 0 L6 6 L-10 6 L-8 0 L-10 -6 L6 -6 Z", class: "fill-map-visited stroke-map-sea", "stroke-width": 1.2, "stroke-linejoin": "round" });
}

function moverElement(index: number, vehicle: Vehicle): { node: HTMLElement; body: SVGElement } {
  const body = element("g", {}, moverGlyph(vehicle));
  const node = anchored(body, 16, { "data-mover": String(index), "data-vehicle": vehicle, "data-flying": "true", ...(vehicle === "plane" ? { "data-plane": String(index) } : {}), ...(vehicle === "car" ? { "data-car": String(index) } : {}), ...(vehicle === "boat" ? { "data-boat": String(index) } : {}) });
  return { node, body };
}

export function createReplayMap(mk: Mk, host: HTMLElement, options: ReplayMapOptions): ReplayMap {
  const { stops, roads, width, height, palette, scale, onFailure, tripId = null, more = [], onView } = options;
  const projection = mercatorFor(stops, width, height, roads, more);
  const legs = legsOf(stops, projection, roads);
  const spots = positions(stops, projection);
  const paths = legs.map(legPath);
  let lastFrame: Frame | null = null;
  let over = false;
  const full: Box = { x: 0, y: 0, w: width, h: height };
  const coordinate = (at: Spot) => {
    const found = projection.invert?.([at.x, at.y]);
    return new mk.Coordinate(lat(found?.[1] ?? 0), found?.[0] ?? 0);
  };
  const coordinates = (points: Spot[]) => points.map(coordinate);
  const style = (color: string, lineWidth: number, extra: Record<string, unknown> = {}) => new mk.Style({ strokeColor: color, lineWidth: lineWidth * scale, lineCap: "round", lineJoin: "round", ...extra });

  let map: MkMap | null = new mk.Map(host, {
    colorScheme: mk.Map.ColorSchemes.Dark, showsMapTypeControl: false, showsZoomControl: false, showsCompass: mk.FeatureVisibility.Hidden,
    showsScale: mk.FeatureVisibility.Hidden, isScrollEnabled: false, isZoomEnabled: false, isRotationEnabled: false,
  });
  const watch = () => onFailure();
  mk.addEventListener("error", watch);

  const ends: (() => void)[] = [];
  const release = () => {
    over = true;
    mk.removeEventListener("error", watch);
    for (const end of ends) { try { end(); } catch { continue; } }
    try { map?.destroy(); } catch { map = null; }
    map = null;
  };
  let stopMarks: { annotation: MkAnnotation; ping: SVGElement; shown: boolean }[];
  try {
    stopMarks = stops.map((stop, i) => {
      const made = stopElement(stop);
      return { annotation: new mk.Annotation(coordinate(spots[i]), () => made.node, { visible: true }), ping: made.ping, shown: false };
    });
    if (stopMarks.length > 0) {
      map?.addAnnotation(stopMarks[0].annotation);
      stopMarks[0].shown = true;
    }
  } catch (e) {
    release();
    throw e;
  }
  ends.push(() => { for (const mark of stopMarks) if (mark.shown) map?.removeAnnotation(mark.annotation); });
  let mover: { leg: number; annotation: MkAnnotation; body: SVGElement } | null = null;
  const clearMover = () => {
    if (!mover) return;
    const gone = mover.annotation;
    mover = null;
    map?.removeAnnotation(gone);
  };
  ends.push(clearMover);
  const legMarks = new Map<number, { overlay: MkOverlay; done: number }>();
  let seen = "";

  const rectOf = (box: Box) => {
    const r = mapRectFor(projection, box);
    return new mk.MapRect(r.x, r.y, r.width, r.height);
  };

  const draw = (frame: Frame) => {
    if (!map) return;
    const { progress, playing, calm } = frame;
    const box = calm ? full : cameraAt(stops, spots, width, height, progress, legs);
    const view = `${box.x.toFixed(2)},${box.y.toFixed(2)},${box.w.toFixed(2)},${box.h.toFixed(2)}`;
    if (view !== seen) {
      seen = view;
      map.setVisibleMapRectAnimated(rectOf(box), false);
      host.setAttribute("data-zoomed", String(box.w < width - 0.5));
      onView?.(box);
    }
    const now = calm ? stops.length - 1 : activeStop(stops.length, progress);
    stopMarks.forEach((mark, i) => {
      const show = calm || reached(i, stops.length, progress);
      if (show && !mark.shown) { map?.addAnnotation(mark.annotation); mark.shown = true; }
      else if (!show && mark.shown) { map?.removeAnnotation(mark.annotation); mark.shown = false; }
      mark.ping.style.display = !calm && playing && i === now ? "" : "none";
    });
    let movingLeg = -1;
    legs.forEach((leg, i) => {
      const done = calm ? 1 : legProgress(i, stops.length, progress);
      const mark = legMarks.get(i);
      if (done <= 0) {
        if (mark) { map?.removeOverlay(mark.overlay); legMarks.delete(i); }
      } else if (!mark) {
        const overlay = new mk.PolylineOverlay(coordinates(cutAt(paths[i], done)), { style: style(leg.flight ? palette.route : palette.stay, leg.flight ? FLIGHT_WIDTH : GROUND_WIDTH) });
        map?.addOverlay(overlay);
        legMarks.set(i, { overlay, done });
      } else if (mark.done !== done) {
        mark.overlay.points = coordinates(cutAt(paths[i], done));
        mark.done = done;
      }
      const moving = done > 0 && done < 1;
      if (moving && movingLeg < 0) movingLeg = i;
    });
    if (movingLeg < 0 || (mover && mover.leg !== movingLeg)) clearMover();
    if (movingLeg >= 0) {
      const leg = legs[movingLeg];
      if (!mover) {
        const made = moverElement(movingLeg, leg.vehicle);
        const annotation = new mk.Annotation(coordinate(spots[movingLeg]), () => made.node, { visible: true });
        map.addAnnotation(annotation);
        mover = { leg: movingLeg, annotation, body: made.body };
      }
      const at = moverAt(leg, legProgress(movingLeg, stops.length, progress));
      mover.annotation.coordinate = coordinate(at);
      mover.body.setAttribute("transform", `rotate(${at.angle.toFixed(1)}) scale(${MOVER_SCALE})`);
    }
  };

  const adopt = (index: number, route: number[][]) => {
    if (over) return;
    const points: Spot[] = [spots[index]];
    for (const [la, lo] of route) {
      const at = projection([lo, la]);
      if (at) points.push({ x: at[0], y: at[1] });
    }
    points.push(spots[index + 1]);
    if (points.length < 4) return;
    const track = pathOf(points);
    legs[index].road = track;
    paths[index] = track;
    const mark = legMarks.get(index);
    if (mark) mark.done = -1;
    if (lastFrame) {
      try { draw(lastFrame); } catch { onFailure(); }
    }
  };
  const driven: { index: number; drive: Drive }[] = [];
  legs.forEach((leg, i) => {
    if (leg.vehicle !== "car" || stops[i + 1].via !== null) return;
    const [a, b] = [stops[i], stops[i + 1]];
    if (a.latitude === b.latitude && a.longitude === b.longitude) return;
    driven.push({ index: i, drive: { from: a, to: b } });
  });
  drivingRoutes(mk, tripId, driven.map((d) => d.drive)).forEach((answer, n) => {
    void answer.then((route) => { if (route) adopt(driven[n].index, route); });
  });

  return {
    update(frame) {
      lastFrame = frame;
      try { draw(frame); } catch { onFailure(); }
    },
    destroy: release,
  };
}
