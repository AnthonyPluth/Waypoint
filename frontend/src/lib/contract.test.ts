// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiCall } from "./contract";

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

describe("apiCall", () => {
  it("sends what api() does, for a route the contract covers", async () => {
    fetchMock.mockReturnValue(reply({ version: "1.0", database: "sqlite", user: null, last_backup: null, review_count: 0 }));
    const r = await apiCall<"GET /api/state">("/api/state");
    expect(r.database).toBe("sqlite");
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe("GET");
    expect(init.headers).not.toHaveProperty("X-Waypoint");
  });

  it("checks the address, the method, the body and the reply against the contract (npm run check)", async () => {
    fetchMock.mockImplementation(() => reply({}));
    const s = await apiCall<"GET /api/state">("/api/state");
    expect(s.version satisfies string).toBeUndefined();
    // @ts-expect-error: not a field of the reply
    expect(s.versions).toBeUndefined();
    // @ts-expect-error: the route's address, not another's
    await apiCall<"GET /api/state">("/api/backup");
    // @ts-expect-error: a POST route says so
    await apiCall<"POST /api/restore">("/api/restore");
    // @ts-expect-error: a GET sends no body
    await apiCall<"GET /api/state">("/api/state", { body: { a: 1 } });
    // @ts-expect-error: only the routes the contract covers
    await apiCall<"GET /api/nothing">("/api/nothing");
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });
});
