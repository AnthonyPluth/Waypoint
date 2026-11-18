import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiCall } from "./contract";
import { CARD_TRIPS, CARD_WAIT_MS, clearSnapshots, snapshotFor } from "./map-snapshots";

vi.mock("./contract", () => ({ apiCall: vi.fn() }));
const server = vi.mocked(apiCall);

const snap = (trip: number, width = 352, height = 168) => ({ trip_id: trip, url: `https://maps.example/snapshot?trip-${trip}`, center: { latitude: 40.27, longitude: -108.43 }, zoom: 6, width, height });
const reply = (trips: number[], width = 352, height = 168) => ({ snapshots: trips.map((t) => snap(t, width, height)) });
const queries = () => server.mock.calls.map(([path]) => new URLSearchParams(String(path).split("?")[1]));
const settle = () => vi.advanceTimersByTimeAsync(CARD_WAIT_MS + 10);

beforeEach(() => {
  vi.useFakeTimers();
  clearSnapshots();
  server.mockReset();
  server.mockImplementation(async (path) => {
    const q = new URLSearchParams(String(path).split("?")[1]);
    return reply(q.getAll("trip").map(Number), Number(q.get("w")), Number(q.get("h"))) as never;
  });
});
afterEach(() => { vi.useRealTimers(); });

describe("asking for the addresses of the cards on screen", () => {
  it("sends the cards that mount together in one request, with their size and the browser's language", async () => {
    const got = [snapshotFor(1, 352, 168), snapshotFor(2, 352, 168), snapshotFor(3, 352, 168)];
    await settle();
    expect(server).toHaveBeenCalledTimes(1);
    expect(server.mock.calls[0][0]).toMatch(/^\/api\/map-snapshots\?/);
    expect(queries()[0].getAll("trip")).toEqual(["1", "2", "3"]);
    expect([queries()[0].get("w"), queries()[0].get("h"), queries()[0].get("lang")]).toEqual(["352", "168", navigator.language]);
    expect((await Promise.all(got)).map((s) => s?.url)).toEqual([1, 2, 3].map((t) => snap(t).url));
  });

  it("asks at most twelve trips at a time, and a different size apart", async () => {
    const many = Array.from({ length: CARD_TRIPS + 3 }, (_, i) => snapshotFor(i + 1, 352, 168));
    const roomy = snapshotFor(99, 400, 216);
    await settle();
    expect(queries().map((q) => [q.getAll("trip").length, q.get("w")])).toEqual([[12, "352"], [3, "352"], [1, "400"]]);
    expect((await Promise.all(many)).every((s) => s !== null)).toBe(true);
    expect((await roomy)?.width).toBe(400);
  });

  it("asks once for a card however often it is asked, and doesn't ask again for what it already has", async () => {
    const first = snapshotFor(1, 352, 168);
    expect(snapshotFor(1, 352, 168)).toBe(first);
    await settle();
    await first;
    await snapshotFor(1, 352, 168);
    await settle();
    expect(server).toHaveBeenCalledTimes(1);
  });

  it("answers null for a trip the reply leaves out, and doesn't ask for it again until the page reloads", async () => {
    server.mockResolvedValue({ snapshots: [snap(1)] } as never);
    const [one, two] = [snapshotFor(1, 352, 168), snapshotFor(2, 352, 168)];
    await settle();
    expect((await one)?.url).toBe(snap(1).url);
    expect(await two).toBeNull();
    expect(await snapshotFor(2, 352, 168)).toBeNull();
    await settle();
    expect(server).toHaveBeenCalledTimes(1);
  });

  it("answers null when the request fails, and doesn't retry", async () => {
    server.mockRejectedValue(new Error("down"));
    const one = snapshotFor(1, 352, 168);
    await settle();
    expect(await one).toBeNull();
    expect(await snapshotFor(1, 352, 168)).toBeNull();
    await settle();
    expect(server).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["not an object", null],
    ["no snapshots", {}],
    ["an address that isn't a string", { snapshots: [{ ...snap(1), url: 5 }] }],
    ["an address that isn't https", { snapshots: [{ ...snap(1), url: "javascript:alert(1)" }] }],
    ["an address on a plain connection", { snapshots: [{ ...snap(1), url: "http://maps.example/snapshot" }] }],
    ["a centre that isn't a place", { snapshots: [{ ...snap(1), center: { latitude: "x", longitude: 1 } }] }],
    ["a zoom that isn't a number", { snapshots: [{ ...snap(1), zoom: "6" }] }],
    ["a size that isn't a number", { snapshots: [{ ...snap(1), width: null }] }],
  ])("treats %s as no map", async (_name, bad) => {
    server.mockResolvedValue(bad as never);
    const one = snapshotFor(1, 352, 168);
    await settle();
    expect(await one).toBeNull();
  });

  it("ignores a snapshot for a trip nobody asked about", async () => {
    server.mockResolvedValueOnce({ snapshots: [snap(1), snap(77)] } as never);
    server.mockResolvedValue({ snapshots: [] } as never);
    const [one] = [snapshotFor(1, 352, 168)];
    await settle();
    expect((await one)?.url).toBe(snap(1).url);
    const stranger = snapshotFor(77, 352, 168);
    await settle();
    expect(await stranger).toBeNull();
  });

  it("forgets everything when cleared, and answers the waiting cards with no map", async () => {
    const waiting = snapshotFor(1, 352, 168);
    clearSnapshots();
    expect(await waiting).toBeNull();
    await settle();
    expect(server).not.toHaveBeenCalled();
    const again = snapshotFor(1, 352, 168);
    await settle();
    expect((await again)?.url).toBe(snap(1).url);
  });

  it("keeps an answer that arrives after a clear out of the next page", async () => {
    let release: (v: unknown) => void = () => {};
    server.mockImplementationOnce(() => new Promise((r) => { release = r; }) as never);
    const old = snapshotFor(1, 352, 168);
    await settle();
    clearSnapshots();
    release(reply([1]));
    expect(await old).toBeNull();
    const fresh = snapshotFor(1, 352, 168);
    await settle();
    expect((await fresh)?.url).toBe(snap(1).url);
    expect(server).toHaveBeenCalledTimes(2);
  });
});
