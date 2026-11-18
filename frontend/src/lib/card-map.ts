import { BOW, LOCAL_BOW, driveKey, type Spot, type Stop } from "./route-replay";
import { isDrive, type RoutePath } from "./driving-routes";

export type Place = { latitude: number; longitude: number };
export type Frame = { center: Place; zoom: number; width: number; height: number };
export type CardLeg = { d: string; flight: boolean };

const WORLD = 256;
const MAX_LATITUDE = 85.0511;

const worldX = (longitude: number): number => ((longitude + 180) / 360) * WORLD;
const worldY = (latitude: number): number => {
  const clamped = Math.max(-MAX_LATITUDE, Math.min(MAX_LATITUDE, latitude));
  return (0.5 - Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI) / 360)) / (2 * Math.PI)) * WORLD;
};

export function project(place: Place, frame: Frame): Spot {
  const scale = 2 ** frame.zoom;
  const across = worldX(place.longitude) - worldX(frame.center.longitude);
  const near = across - Math.round(across / WORLD) * WORLD;
  return {
    x: frame.width / 2 + near * scale,
    y: frame.height / 2 + (worldY(place.latitude) - worldY(frame.center.latitude)) * scale,
  };
}

export const cardSpots = (stops: Place[], frame: Frame): Spot[] => stops.map((s) => project(s, frame));

const at = (p: Spot): string => `${p.x.toFixed(1)},${p.y.toFixed(1)}`;

export function cardLegs(stops: Stop[], spots: Spot[], roads: ReadonlyMap<string, RoutePath>, frame: Frame): CardLeg[] {
  const out: CardLeg[] = [];
  for (let i = 1; i < stops.length; i++) {
    const from = spots[i - 1], to = spots[i];
    const flight = stops[i].via === "flight";
    const road = isDrive(stops[i - 1], stops[i]) ? roads.get(driveKey(stops[i - 1], stops[i])) : undefined;
    if (road) {
      out.push({ flight, d: road.map(([latitude, longitude], k) => `${k === 0 ? "M" : "L"}${at(project({ latitude, longitude }, frame))}`).join(" ") });
      continue;
    }
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    const bow = length * (flight ? BOW : stops[i].via === null ? 0 : LOCAL_BOW);
    if (bow === 0 || length === 0) { out.push({ flight, d: `M${at(from)} L${at(to)}` }); continue; }
    const control = { x: (from.x + to.x) / 2 + ((to.y - from.y) / length) * bow, y: (from.y + to.y) / 2 - ((to.x - from.x) / length) * bow };
    out.push({ flight, d: `M${at(from)} Q${at(control)} ${at(to)}` });
  }
  return out;
}
