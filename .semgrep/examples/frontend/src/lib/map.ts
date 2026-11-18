// ok: waypoint-no-bundled-map-outlines
const { feature } = await import("topojson-client");
// ok: waypoint-no-bundled-map-outlines
const atlas = await import("world-atlas/countries-50m.json");
// ruleid: waypoint-no-bundled-map
const drawn = geoPath(projection);
