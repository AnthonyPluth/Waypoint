import { api, type Options } from "./api";
import type { Endpoints } from "./api-types";

type Route = keyof Endpoints;
type MethodOf<R extends Route> = R extends `${infer M} ${string}` ? M : never;
type Filled<P extends string> = P extends `${infer A}{id}${infer B}` ? `${A}${string}${Filled<B>}` : P;
type AddressOf<R extends Route> = R extends `${string} ${infer P}` ? Filled<P> | `${Filled<P>}?${string}` : never;
type RouteOptions<R extends Route> = Omit<Options, "method" | "body">
  & (MethodOf<R> extends "GET" ? { method?: "GET" } : { method: MethodOf<R> })
  & ([Endpoints[R]["body"]] extends [never] ? { body?: never } : { body: Endpoints[R]["body"] });

export function apiCall<R extends Route>(
  path: AddressOf<R>, ...[opts]: object extends RouteOptions<R> ? [RouteOptions<R>?] : [RouteOptions<R>]
): Promise<Endpoints[R]["reply"]> {
  return opts ? api<Endpoints[R]["reply"]>(path, opts as Options) : api<Endpoints[R]["reply"]>(path);
}
