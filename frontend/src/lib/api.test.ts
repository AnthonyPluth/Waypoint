// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, newPage } from "./api";

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("GETs JSON without the CSRF header", async () => {
    fetchMock.mockReturnValue(reply({ a: 1 }));
    expect(await api("/api/x")).toEqual({ a: 1 });
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe("GET");
    expect(init.headers).not.toHaveProperty("X-Waypoint");
  });

  it("sends state changes with the CSRF header and a JSON body", async () => {
    fetchMock.mockReturnValue(reply({ ok: true }));
    await api("/api/x", { method: "POST", body: { n: 2 } });
    const init = fetchMock.mock.calls[0][1];
    expect(init.headers).toEqual({ "X-Waypoint": "1", "Content-Type": "application/json" });
    expect(init.body).toBe('{"n":2}');
  });

  it("throws the server's error message with the status", async () => {
    fetchMock.mockReturnValue(reply({ error: "Nope" }, 400));
    const err = await api("/api/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ message: "Nope", status: 400 });
  });

  it("falls back to a generic message when the error reply isn't JSON", async () => {
    fetchMock.mockReturnValue(Promise.resolve(new Response("<html>Teapot</html>", { status: 418 })));
    await expect(api("/api/x")).rejects.toMatchObject({ message: "Request failed (418)", status: 418 });
  });

  it("says Waypoint is restarting when a proxy answers for it", async () => {
    for (const status of [502, 503, 504]) {
      fetchMock.mockReturnValue(Promise.resolve(new Response("<html>Bad gateway</html>", { status })));
      await expect(api("/api/x")).rejects.toMatchObject({ message: "Waypoint is restarting or unreachable. Try again in a moment.", status });
    }
    fetchMock.mockReturnValue(reply({ error: "Plaid is down" }, 502));
    await expect(api("/api/x")).rejects.toMatchObject({ message: "Plaid is down", status: 502 });
  });

  it("sends a file as it is, not as JSON, with the CSRF header", async () => {
    fetchMock.mockReturnValue(reply({ ok: true }));
    const file = new File([new Uint8Array([0x1f, 0x8b])], "backup.gz");
    await api("/api/restore", { method: "POST", body: file });
    const init = fetchMock.mock.calls[0][1];
    expect(init.headers).toEqual({ "X-Waypoint": "1", "Content-Type": "application/octet-stream" });
    expect(init.body).toBe(file);
  });

  it("names a refusal that says nothing with `failed`, and still shows the server's own words", async () => {
    fetchMock.mockReturnValue(Promise.resolve(new Response("<html>Oops</html>", { status: 500 })));
    await expect(api("/api/restore", { method: "POST", body: {}, failed: "Restore failed" })).rejects.toMatchObject({ message: "Restore failed (500)", status: 500 });
    fetchMock.mockReturnValue(reply({ error: "That file isn't a Waypoint backup." }, 400));
    await expect(api("/api/restore", { method: "POST", body: {}, failed: "Restore failed" })).rejects.toMatchObject({ message: "That file isn't a Waypoint backup." });
  });

  it("sends you to sign in again, and back here, when the session has expired", async () => {
    fetchMock.mockReturnValue(reply({}, 401));
    const fake = { href: "", pathname: "/", hash: "#budget" };
    vi.stubGlobal("location", fake);
    await expect(api("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(fake.href).toBe("/auth/login?next=" + encodeURIComponent("/#budget"));
  });

  it("tells the app first, and stays on the page when Waypoint was only checking in or the app says so", async () => {
    fetchMock.mockImplementation(() => reply({}, 401));
    const fake = { href: "", pathname: "/", hash: "#budget" };
    vi.stubGlobal("location", fake);
    const seen: boolean[] = [];
    const listener = (e: CustomEvent<{ background: boolean }>) => { seen.push(e.detail.background); };
    window.addEventListener("waypoint:signed-out", listener);
    await expect(api("/api/state", { keep: true, background: true }))
      .rejects.toMatchObject({ message: "Your session expired. Sign in again to keep going.", status: 401 });
    expect(fake.href).toBe("");
    const cancel = (e: Event) => e.preventDefault();
    window.addEventListener("waypoint:signed-out", cancel);
    await expect(api("/api/x", { method: "POST", body: { split: 1 } })).rejects.toMatchObject({ status: 401 });
    expect(fake.href).toBe("");
    expect(seen).toEqual([true, false]);
    window.removeEventListener("waypoint:signed-out", listener);
    window.removeEventListener("waypoint:signed-out", cancel);
  });

  it("never answers a read the page moved on from", async () => {
    let release!: (r: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>((r) => { release = r; }));
    const settled = vi.fn();
    api("/api/slow").then(settled, settled);
    newPage();
    release(new Response("{}"));
    await new Promise((r) => setTimeout(r, 10));
    expect(settled).not.toHaveBeenCalled();
  });

  it("lets a read with keep finish even after the page changed", async () => {
    let release!: (r: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>((r) => { release = r; }));
    const p = api("/api/state", { keep: true });
    newPage();
    release(new Response('{"ok":1}'));
    expect(await p).toEqual({ ok: 1 });
    expect(fetchMock.mock.calls[0][1].signal).toBeUndefined();
  });

  it("does not cancel writes when the page changes", async () => {
    fetchMock.mockReturnValue(reply({ done: true }));
    const p = api("/api/x", { method: "POST" });
    newPage();
    expect(await p).toEqual({ done: true });
  });

  it("says Waypoint can't be reached, in the same words in every browser, when the page hasn't moved", async () => {
    for (const message of ["Failed to fetch", "Load failed", "NetworkError when attempting to fetch resource."]) {
      fetchMock.mockRejectedValue(new TypeError(message));
      await expect(api("/api/x")).rejects.toMatchObject({ message: "Can’t reach Waypoint. Check your connection and try again.", status: 0 });
    }
  });

  it("never answers a read the page moved on from, even when it failed", async () => {
    let fail!: (e: Error) => void;
    fetchMock.mockReturnValue(new Promise<Response>((_, r) => { fail = r; }));
    const settled = vi.fn();
    api("/api/slow").then(settled, settled);
    newPage();
    fail(new TypeError("Failed to fetch"));
    await new Promise((r) => setTimeout(r, 10));
    expect(settled).not.toHaveBeenCalled();
  });
});
