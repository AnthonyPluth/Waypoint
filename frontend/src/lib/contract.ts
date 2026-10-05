// Calls to the routes the API contract covers (lib/api-types.ts, generated from the backend's waypoint/server/contract.py):
// a call names its route, and its address, method, body and reply are checked against the contract. Use apiCall for a
// covered route, rather than api() with a reply type written by hand. It's api() underneath (and a test that mocks
// $lib/api's api() sees these calls too).
import { api, type Options } from "./api";
import type { Endpoints } from "./api-types";

type Route = keyof Endpoints;
type MethodOf<R extends Route> = R extends `${infer M} ${string}` ? M : never;
/** A route's address with its {id}s filled in, and a query string after it if any. */
type Filled<P extends string> = P extends `${infer A}{id}${infer B}` ? `${A}${string}${Filled<B>}` : P;
type AddressOf<R extends Route> = R extends `${string} ${infer P}` ? Filled<P> | `${Filled<P>}?${string}` : never;
type RouteOptions<R extends Route> = Omit<Options, "method" | "body">
  & (MethodOf<R> extends "GET" ? { method?: "GET" } : { method: MethodOf<R> })
  & ([Endpoints[R]["body"]] extends [never] ? { body?: never } : { body: Endpoints[R]["body"] });

/** api(), for a route the contract covers, named as `METHOD /path`: `apiCall<"GET /api/budget">(address)`, the address
 *  that route answers (its {id}s filled in, and a query string after it if any). */
export function apiCall<R extends Route>(
  path: AddressOf<R>, ...[opts]: object extends RouteOptions<R> ? [RouteOptions<R>?] : [RouteOptions<R>]
): Promise<Endpoints[R]["reply"]> {
  return opts ? api<Endpoints[R]["reply"]>(path, opts as Options) : api<Endpoints[R]["reply"]>(path);
}
