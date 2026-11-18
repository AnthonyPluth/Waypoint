import { geoPath } from "d3-geo";

// ruleid: waypoint-no-bundled-map
const path = geoPath(projection);
// ruleid: waypoint-no-bundled-map
const spaced = geoPath (projection);
// ok: waypoint-no-bundled-map
const contained = geoContains(feature, point);
// ruleid: waypoint-no-bundled-map-outlines
import atlas from "world-atlas/countries-110m.json";
// ruleid: waypoint-no-bundled-map-outlines
import { feature } from "topojson-client";
// ruleid: waypoint-no-bundled-map-outlines
const states = await import("us-atlas/states-10m.json");
// ok: waypoint-no-bundled-map-outlines
import { loadStates } from "$lib/map";
