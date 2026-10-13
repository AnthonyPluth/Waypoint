// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const lib = vi.hoisted(() => {
  const state = { made: [] as FakeMap[], throwOnCreate: false };
  class FakeMap {
    handlers: Record<string, (() => void)[]> = {};
    jumps: unknown[] = [];
    resizes = 0;
    removed = false;
    constructor(public options: Record<string, unknown>) {
      if (state.throwOnCreate) throw new Error("no WebGL");
      state.made.push(this);
    }
    once(name: string, f: () => void) { (this.handlers[name] ??= []).push(f); }
    on(name: string, f: () => void) { (this.handlers[name] ??= []).push(f); }
    emit(name: string) { this.handlers[name]?.forEach((f) => f()); }
    jumpTo(o: unknown) { this.jumps.push(o); }
    resize() { this.resizes++; }
    remove() { this.removed = true; }
  }
  return { state, FakeMap, addProtocol: vi.fn(), removeProtocol: vi.fn() };
});
const made = lib.state.made;
const { addProtocol, removeProtocol } = lib;

vi.mock("maplibre-gl", () => ({ Map: lib.FakeMap, addProtocol: lib.addProtocol, removeProtocol: lib.removeProtocol }));
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));
vi.mock("pmtiles", () => ({ Protocol: class { tile = () => {}; } }));

import ReplayBasemap from "./ReplayBasemap.svelte";

let observers: { callback: () => void; disconnected: boolean }[] = [];
beforeEach(() => {
  made.length = 0;
  lib.state.throwOnCreate = false;
  addProtocol.mockClear();
  removeProtocol.mockClear();
  observers = [];
  vi.stubGlobal("ResizeObserver", class {
    entry = { callback: () => {}, disconnected: false };
    constructor(callback: () => void) { this.entry.callback = callback; observers.push(this.entry); }
    observe() {}
    disconnect() { this.entry.disconnected = true; }
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ReplayBasemap", () => {
  it("makes a map that can't be moved by hand, from Waypoint's own style, and registers the pmtiles protocol", () => {
    render(ReplayBasemap, { center: [-93, 45], zoom: 4, onfail: vi.fn() });
    expect(made).toHaveLength(1);
    const o = made[0].options as { interactive: boolean; attributionControl: boolean; center: number[]; zoom: number; maxZoom: number; style: { sources: Record<string, { url: string }> } };
    expect([o.interactive, o.attributionControl, o.center, o.zoom, o.maxZoom]).toEqual([false, false, [-93, 45], 4, 10]);
    expect(o.style.sources.protomaps.url).toBe(`pmtiles://${location.origin}/api/map/tiles`);
    expect(addProtocol).toHaveBeenCalledWith("pmtiles", expect.any(Function));
  });

  it("moves the camera when the box moves and keeps the map the size of its container", async () => {
    const { rerender } = render(ReplayBasemap, { center: [-93, 45], zoom: 4, onfail: vi.fn() });
    await rerender({ center: [-74, 40], zoom: 6, onfail: vi.fn() });
    expect(made[0].jumps.at(-1)).toEqual({ center: [-74, 40], zoom: 6 });
    observers[0].callback();
    expect(made[0].resizes).toBe(1);
  });

  it("credits OpenStreetMap contributors and Protomaps, with a link that opens safely", () => {
    render(ReplayBasemap, { center: [0, 0], zoom: 1, onfail: vi.fn() });
    const credit = screen.getByTestId("map-credit");
    expect(credit).toHaveTextContent("© OpenStreetMap contributors · Protomaps");
    const link = screen.getByRole("link", { name: "© OpenStreetMap contributors" });
    expect(link).toHaveAttribute("href", "https://www.openstreetmap.org/copyright");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("says so when the map can't be made, so the bundled map takes over", () => {
    lib.state.throwOnCreate = true;
    const onfail = vi.fn();
    render(ReplayBasemap, { center: [0, 0], zoom: 1, onfail });
    expect(onfail).toHaveBeenCalledTimes(1);
  });

  it("says so when the style or tiles fail before the map has loaded, and not for a tile that fails after", () => {
    const onfail = vi.fn();
    render(ReplayBasemap, { center: [0, 0], zoom: 1, onfail });
    made[0].emit("error");
    expect(onfail).toHaveBeenCalledTimes(1);
    onfail.mockClear();
    made[0].emit("load");
    made[0].emit("error");
    expect(onfail).not.toHaveBeenCalled();
  });

  it("cleans up the map, the observer and the protocol when it goes", () => {
    const { unmount } = render(ReplayBasemap, { center: [0, 0], zoom: 1, onfail: vi.fn() });
    unmount();
    expect(made[0].removed).toBe(true);
    expect(observers[0].disconnected).toBe(true);
    expect(removeProtocol).toHaveBeenCalledWith("pmtiles");
  });
});
