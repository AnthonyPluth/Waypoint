import source from "./data.json";
import type { Options } from "../src/lib/api";
import type { Trip, Person, Review, Stats, TripPlaces, FlightStatusList } from "../src/lib/api-types";

export const data = source as unknown as { asOf: string; trips: Trip[]; people: Person[]; loyalty: unknown[]; programs: unknown; numbers: Record<string,string>; stats: Record<string,Stats>; places: Record<string,TripPlaces>; airports: Record<string,unknown>; review: Review; emails: Record<string,unknown[]>; previews: Record<string,unknown>; flight_status: FlightStatusList };
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly data: Record<string,unknown> = {}) { super(message); }
}
export function newPage(): void {}
export function onDenied(_fn: () => Promise<void>): void {}
export function signInUrl(): string { return "#settings/account"; }
export async function apiImage(_path: string): Promise<string> { throw new ApiError("Images are unavailable in the read-only demo",403); }
export async function api<T = unknown>(path: string, options: Options = {}): Promise<T> {
  const url = new URL(path,"https://static-demo.invalid");
  const method = options.method ?? "GET";
  const reveal = /^\/api\/loyalty\/(\d+)\/reveal$/.exec(url.pathname);
  if (method === "POST" && reveal) return {number:data.numbers[reveal[1]]} as T;
  if (method !== "GET") throw new ApiError("This demo is read only. Changes and connections are disabled.",403);
  const trip = /^\/api\/trips\/(\d+)(\/places)?$/.exec(url.pathname);
  const emails = /^\/api\/segments\/(\d+)\/emails$/.exec(url.pathname);
  const preview = /^\/api\/review\/(\d+)\/preview$/.exec(url.pathname);
  const airport = /^\/api\/airports\/([A-Z]{3})$/.exec(url.pathname);
  let result: unknown;
  if (trip) result = trip[2] ? data.places[trip[1]] : data.trips.find(item=>item.id === Number(trip[1]));
  else if (emails) result = {emails:data.emails[emails[1]] ?? []};
  else if (preview) result = data.previews[preview[1]];
  else if (airport) result = data.airports[airport[1]];
  else {
    const replies: Record<string,unknown> = {
      "/api/state":{version:"Static demo",database:"sqlite",user:{name:"Jane Doe",email:"jane.doe@example.com",local:true},last_backup:null,review_count:data.review.items.length + data.review.matches.length + data.review.who.length,person_id:1,ai:false,show_costs:true},
      "/api/trips":{trips:data.trips},
      "/api/people":{people:data.people},
      "/api/people/claim-suggestions":{guests:[]},
      "/api/loyalty":{loyalty:data.loyalty,programs:data.programs,conflicts:[]},
      "/api/review":data.review,
      "/api/stats":data.stats[`${url.searchParams.get("person") || "all"}/${url.searchParams.get("year") || "all"}`] ?? data.stats["all/all"],
      "/api/airports":{airports:Object.values(data.airports)},
      "/api/flight-status":data.flight_status,
      "/api/mailboxes":{configured:false,mailboxes:[]},
      "/api/ai":{mode:"off",ollama_url:"",ollama_model:"",openrouter_model:"",key:null,auto:false},
      "/api/home":{city:"New York",state:"NY",zip:"10001",country:"US",saved:true,placed:true,latitude:40.7128,longitude:-74.006,zone:"America/New_York"},
      "/api/distance-unit":{distance_unit:"mi"},
      "/api/logodev":{configured:false,searchable:false,with_logo:0,unknown:0,waiting:0,last_error:null},
      "/api/mcp-settings":{allow_writes:false,oauth:false,url:null,reason:"External integrations are disabled in the static demo.",connections:[]},
      "/api/reminders":{public_key:"",check_in:false,day_of:false,devices:[],feed:false},
      "/api/offline":{trips:[]}
    };
    result = replies[url.pathname];
  }
  if (result === undefined || result === null) throw new ApiError("No bundled demo example for this view",404);
  return structuredClone(result) as T;
}
