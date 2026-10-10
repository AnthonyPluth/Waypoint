// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ Toaster: vi.fn(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { ApiError, api } from "$lib/api";
import { app, boot } from "$lib/app.svelte";
import { dropEarly } from "$lib/early";
import { segment, state, trip } from "./test/fixtures";
import App from "./App.svelte";

const london = trip([segment({ id: 1, origin: "JFK", destination: "LHR", start_local: "2099-11-20T19:00", end_local: "2099-11-21T07:10" })]);

beforeEach(() => {
  vi.mocked(api).mockReset();
  app.state = null; app.bootError = "";
  location.hash = "#upcoming";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  dropEarly();
});
afterEach(() => { app.state = null; dropEarly(); });

describe("trying again after the first load failed", () => {
  it("shows the trips, not the failure of the early read that went with the first try", async () => {
    let online = false;
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (!online) throw new ApiError("Can’t reach Waypoint. Check your connection and try again.", 0);
      return path === "/api/state" ? state() : path === "/api/flight-status" ? { enabled: false, statuses: [] } : { trips: [london], people: [], loyalty: [], guests: [] };
    }) as never);
    render(App);
    await boot();
    expect(app.state).toBeNull();
    online = true;
    await boot();
    expect((await screen.findAllByText("LHR")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Request failed|Can’t reach Waypoint/)).toBeNull();
  });
});
