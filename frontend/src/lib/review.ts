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
  topAirports: string[];
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
    topAirports: [...f.airports].sort((x, y) => y.visits - x.visits || x.code.localeCompare(y.code)).slice(0, 3).map((a) => a.code),
    nights: stats.stays.nights,
    cruises: { count: stats.cruises.count, nights: stats.cruises.nights, seaDays: stats.cruises.sea_days },
    map: { dots: world.dots.map((d) => ({ x: d.x, y: d.y, r: d.r })), arcs: world.arcs.map((a) => ({ d: a.d, width: a.width })) },
  };
}

export type ImageInputs = Pick<ReviewFacts, "year" | "flights" | "distance" | "airTime" | "nights" | "countries" | "topAirports" | "map"> & { topRoute: { a: string; b: string } | null };

export const imageInputs = (facts: ReviewFacts): ImageInputs => ({
  year: facts.year, flights: facts.flights, distance: facts.distance, airTime: facts.airTime, nights: facts.nights,
  countries: [...facts.countries], topAirports: [...facts.topAirports],
  topRoute: facts.topRoute ? { a: facts.topRoute.a, b: facts.topRoute.b } : null,
  map: { dots: facts.map.dots.map((d) => ({ x: d.x, y: d.y, r: d.r })), arcs: facts.map.arcs.map((a) => ({ d: a.d, width: a.width })) },
});

export function imageSummary(inputs: ImageInputs): string[] {
  const countries = inputs.countries.length;
  return [
    `The year, ${inputs.year}`,
    `${inputs.distance} travelled, ${count(inputs.flights)} ${inputs.flights === 1 ? "flight" : "flights"} and ${inputs.airTime} in the air`,
    `${count(inputs.nights)} ${inputs.nights === 1 ? "night" : "nights"} away`,
    `${countries} ${countries === 1 ? "country" : "countries"}${countries ? `: ${inputs.countries.join(", ")}` : ""}`,
    ...(inputs.topRoute ? [`Top route: ${inputs.topRoute.a} – ${inputs.topRoute.b}`] : []),
    ...(inputs.topAirports.length ? [`Top airports: ${inputs.topAirports.join(", ")}`] : []),
    "The map of the airports and routes",
  ];
}

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const INK = "#f3f5f9", MUTED = "#9aa4b8", ACCENT = "#8fc2ff", SIGNAL = "#f6b73c", BG = "#07090e", LAND = "#1c2230", VISITED = "#3d7bc7", EDGE = "#343c52";
const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

export function mapMarkup(facts: Pick<ReviewFacts, "map">, outlines: { d: string; visited: boolean }[]): string {
  const land = outlines.map((o) => `<path d="${o.d}" fill="${o.visited ? VISITED : LAND}" stroke="${EDGE}" stroke-width="0.5"/>`).join("");
  const arcs = facts.map.arcs.map((a) => `<path d="${a.d}" fill="none" stroke="${ACCENT}" stroke-opacity="0.75" stroke-width="${a.width.toFixed(2)}" stroke-linecap="round"/>`).join("");
  const dots = facts.map.dots.map((d) => `<circle cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="${d.r.toFixed(1)}" fill="${SIGNAL}" stroke="${BG}" stroke-width="1.5"/>`).join("");
  return `${land}${arcs}${dots}`;
}

export const mapSvg = (facts: Pick<ReviewFacts, "map">, outlines: { d: string; visited: boolean }[]): string =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${MAP_WIDTH} ${MAP_HEIGHT}" width="${MAP_WIDTH}" height="${MAP_HEIGHT}"><rect width="${MAP_WIDTH}" height="${MAP_HEIGHT}" rx="24" fill="${BG}"/>${mapMarkup(facts, outlines)}</svg>`;

export const CARD_WIDTH = 1080, CARD_HEIGHT = 1350;

export function cardSvg(inputs: ImageInputs, outlines: { d: string; visited: boolean }[]): string {
  const text = (x: number, y: number, size: number, fill: string, body: string, weight = 400, anchor = "start") =>
    `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${escape(body)}</text>`;
  const stat = (x: number, y: number, value: string, label: string) => text(x, y, 64, INK, value, 700) + text(x, y + 44, 28, MUTED, label.toUpperCase(), 600);
  const countries = inputs.countries.length;
  const route = inputs.topRoute ? `${inputs.topRoute.a} – ${inputs.topRoute.b}` : "—";
  const places = [...inputs.countries.slice(0, 8)].join(" · ") + (countries > 8 ? ` · +${countries - 8} more` : "");
  const airports = inputs.topAirports.length ? `Top airports: ${inputs.topAirports.join(" · ")}` : "";
  const scale = 0.85;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${CARD_WIDTH} ${CARD_HEIGHT}" width="${CARD_WIDTH}" height="${CARD_HEIGHT}">`
    + `<rect width="${CARD_WIDTH}" height="${CARD_HEIGHT}" fill="${BG}"/>`
    + text(60, 110, 30, ACCENT, "YEAR IN REVIEW", 700)
    + text(60, 300, 190, INK, String(inputs.year), 800)
    + stat(60, 440, inputs.distance, "travelled") + stat(60, 590, count(inputs.flights), inputs.flights === 1 ? "flight" : "flights")
    + stat(580, 440, inputs.airTime, "in the air") + stat(580, 590, `${count(inputs.nights)}`, inputs.nights === 1 ? "night away" : "nights away")
    + stat(60, 740, String(countries), countries === 1 ? "country" : "countries") + stat(580, 740, route, "top route")
    + `<g transform="translate(${(CARD_WIDTH - MAP_WIDTH * scale) / 2} 830) scale(${scale})"><rect width="${MAP_WIDTH}" height="${MAP_HEIGHT}" rx="24" fill="${BG}" stroke="${EDGE}" stroke-width="2"/>${mapMarkup(inputs, outlines)}</g>`
    + text(60, 1292, 26, MUTED, places, 400)
    + text(60, 1328, 26, MUTED, airports, 400)
    + text(CARD_WIDTH - 60, 1328, 26, ACCENT, "Waypoint", 700, "end")
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

export function saveImage(png: Blob, filename: string): void {
  const url = URL.createObjectURL(png);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
