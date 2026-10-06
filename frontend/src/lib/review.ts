import type { Stats } from "./api-types";
import { comparisons, count, countryName, distance, duration } from "./stats";
import { MAP_HEIGHT, MAP_WIDTH, mapData, outlinePaths, visitedPoints, worldProjection, type Country } from "./map";

export type ReviewFacts = {
  year: number;
  flights: number;
  distance: string;
  comparisons: string[];
  airTime: string;
  countries: string[];
  newCountries: string[];
  topRoute: { a: string; b: string; flights: number } | null;
  topAirport: string | null;
  nights: number;
  cruises: { count: number; nights: number; seaDays: number };
  map: { dots: { x: number; y: number; r: number }[]; arcs: { d: string; width: number }[] };
};

export function reviewOffered(year: number | null, today: Date): boolean {
  if (year === null) return false;
  const now = today.getFullYear();
  return year < now || (year === now && today.getMonth() === 11);
}

export function reviewFacts(stats: Stats, allTime: Stats | null): ReviewFacts {
  const f = stats.flights, year = stats.year ?? 0;
  const firstSeen = new Map((allTime?.places.countries ?? []).map((c) => [c.name, c.first_visit]));
  const places = stats.places.countries;
  const world = mapData(f);
  return {
    year, flights: f.count, distance: distance(f.distance_km, stats.distance_unit), comparisons: comparisons(f), airTime: duration(f.air_seconds),
    countries: places.map((c) => countryName(c.name)),
    newCountries: places.filter((c) => firstSeen.get(c.name)?.startsWith(`${year}-`)).map((c) => countryName(c.name)),
    topRoute: f.routes[0] ? { a: f.routes[0].a, b: f.routes[0].b, flights: f.routes[0].flights } : null,
    topAirport: f.most_visited_airport,
    nights: stats.stays.nights,
    cruises: { count: stats.cruises.count, nights: stats.cruises.nights, seaDays: stats.cruises.sea_days },
    map: { dots: world.dots.map((d) => ({ x: d.x, y: d.y, r: d.r })), arcs: world.arcs.map((a) => ({ d: a.d, width: a.width })) },
  };
}

export const firstName = (name: string | null | undefined): string | null => name?.trim().split(/\s+/)[0] || null;

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const INK = "#f8fafc", MUTED = "#94a3b8", ACCENT = "#38bdf8", SIGNAL = "#f59e0b", BG = "#0f172a", LAND = "#2a3a52", VISITED = "#1d4e6b";
const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

export function mapMarkup(facts: ReviewFacts, outlines: { d: string; visited: boolean }[]): string {
  const land = outlines.map((o) => `<path d="${o.d}" fill="${o.visited ? VISITED : LAND}" stroke="${BG}" stroke-width="0.5"/>`).join("");
  const arcs = facts.map.arcs.map((a) => `<path d="${a.d}" fill="none" stroke="${ACCENT}" stroke-opacity="0.75" stroke-width="${a.width.toFixed(2)}" stroke-linecap="round"/>`).join("");
  const dots = facts.map.dots.map((d) => `<circle cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="${d.r.toFixed(1)}" fill="${SIGNAL}" stroke="${BG}" stroke-width="1.5"/>`).join("");
  return `${land}${arcs}${dots}`;
}

export const mapSvg = (facts: ReviewFacts, outlines: { d: string; visited: boolean }[]): string =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${MAP_WIDTH} ${MAP_HEIGHT}" width="${MAP_WIDTH}" height="${MAP_HEIGHT}"><rect width="${MAP_WIDTH}" height="${MAP_HEIGHT}" rx="24" fill="${BG}"/>${mapMarkup(facts, outlines)}</svg>`;

export const CARD_WIDTH = 1080, CARD_HEIGHT = 1350;

export function cardSvg(facts: ReviewFacts, outlines: { d: string; visited: boolean }[], name: string | null): string {
  const text = (x: number, y: number, size: number, fill: string, body: string, weight = 400, anchor = "start") =>
    `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${escape(body)}</text>`;
  const stat = (x: number, y: number, value: string, label: string) => text(x, y, 72, INK, value, 700) + text(x, y + 44, 28, MUTED, label.toUpperCase(), 600);
  const countries = facts.countries.length;
  const route = facts.topRoute ? `${facts.topRoute.a} – ${facts.topRoute.b}` : "—";
  const places = [...facts.countries.slice(0, 8)].join(" · ") + (countries > 8 ? ` · +${countries - 8} more` : "");
  const scale = 0.9;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${CARD_WIDTH} ${CARD_HEIGHT}" width="${CARD_WIDTH}" height="${CARD_HEIGHT}">`
    + `<rect width="${CARD_WIDTH}" height="${CARD_HEIGHT}" fill="${BG}"/>`
    + text(60, 110, 30, ACCENT, name ? `${name}’s year in review`.toUpperCase() : "YEAR IN REVIEW", 700)
    + text(60, 300, 190, INK, String(facts.year), 800)
    + stat(60, 440, facts.distance, "travelled") + stat(60, 590, count(facts.flights), facts.flights === 1 ? "flight" : "flights")
    + stat(580, 440, facts.airTime, "in the air") + stat(580, 590, `${count(facts.nights)}`, facts.nights === 1 ? "night away" : "nights away")
    + stat(60, 740, String(countries), countries === 1 ? "country" : "countries") + stat(580, 740, route, "top route")
    + `<g transform="translate(${(CARD_WIDTH - MAP_WIDTH * scale) / 2} 830) scale(${scale})"><rect width="${MAP_WIDTH}" height="${MAP_HEIGHT}" rx="24" fill="${BG}" stroke="${LAND}" stroke-width="2"/>${mapMarkup(facts, outlines)}</g>`
    + text(60, 1322, 26, MUTED, places, 400)
    + text(CARD_WIDTH - 60, 1322, 26, ACCENT, "Waypoint", 700, "end")
    + `</svg>`;
}

export const outlinesFor = (countries: Country[], stats: Stats) => outlinePaths(countries, visitedPoints(stats.flights.airports, stats.stays.pins), worldProjection());

export function svgToPng(svg: string, width = CARD_WIDTH, height = CARD_HEIGHT): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return reject(new Error("This browser can’t draw the picture."));
      ctx.drawImage(img, 0, 0, width, height);
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("This browser can’t make the picture."))), "image/png");
    };
    img.onerror = () => reject(new Error("The picture couldn’t be drawn."));
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  });
}

export async function shareOrDownload(png: Blob, filename: string, title: string): Promise<"shared" | "downloaded" | "cancelled"> {
  const file = new File([png], filename, { type: "image/png" });
  if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title }); return "shared"; }
    catch (err) { if (err instanceof DOMException && err.name === "AbortError") return "cancelled"; throw err; }
  }
  const url = URL.createObjectURL(png);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return "downloaded";
}
