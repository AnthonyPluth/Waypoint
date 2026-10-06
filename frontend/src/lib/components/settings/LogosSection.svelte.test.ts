// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { LogoDevStatus } from "$lib/api-types";
import { toast } from "svelte-sonner";
import LogosSection from "./LogosSection.svelte";

const off: LogoDevStatus = { configured: false, searchable: false, with_logo: 0, unknown: 0, waiting: 0, last_error: null };

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); });

const serve = (current: LogoDevStatus, post: (path: string, b: Record<string, unknown>) => LogoDevStatus | { started: boolean } | Error = () => current) =>
  vi.mocked(api).mockImplementation(async (p: string, opts?: { method?: string; body?: unknown }) => {
    if (opts?.method !== "POST") return current as never;
    const r = post(p, (opts.body ?? {}) as Record<string, unknown>);
    if (r instanceof Error) throw r;
    return r as never;
  });

describe("Settings → Brand logos", () => {
  it("is off to begin with and asks only for the publishable key", async () => {
    serve(off);
    render(LogosSection);
    expect(await screen.findByLabelText("Publishable key")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Secret key/)).toBeNull();
    expect(screen.queryByTestId("logo-status")).toBeNull();
  });

  it("sends the key once and then never has it: the field is empty and says one is saved", async () => {
    serve(off, () => ({ ...off, configured: true, waiting: 3 }));
    render(LogosSection);
    await userEvent.type(await screen.findByLabelText("Publishable key"), "pk_test-1234");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(api).toHaveBeenCalledWith("/api/logodev", { method: "POST", body: { token: "pk_test-1234" } });
    const field = screen.getByLabelText("Publishable key") as HTMLInputElement;
    expect(field.value).toBe("");
    expect(field.placeholder).toMatch(/Saved/);
    expect(screen.getByTestId("logo-status")).toHaveTextContent("3 waiting to be fetched");
  });

  it("shows where logos stand and why a lookup failed", async () => {
    serve({ ...off, configured: true, with_logo: 4, unknown: 1, waiting: 2, last_error: "Oct 06 12:00: Logo.dev refused the key" });
    render(LogosSection);
    const status = await screen.findByTestId("logo-status");
    expect(status).toHaveTextContent("4 brands have a logo");
    expect(status).toHaveTextContent("1 Logo.dev doesn’t know");
    expect(status).toHaveTextContent("Logo.dev refused the key");
  });

  it("asks the server to fetch what is waiting", async () => {
    serve({ ...off, configured: true, waiting: 2 }, () => ({ started: true }));
    render(LogosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Fetch them now" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/logodev/fetch", { method: "POST" }));
  });

  it("saves and forgets the secret key on its own", async () => {
    serve({ ...off, configured: true, searchable: true }, () => ({ ...off, configured: true }));
    render(LogosSection);
    await userEvent.click(await screen.findByRole("button", { name: "Forget the secret key" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/logodev", { method: "POST", body: { clear_secret: true } }));
  });

  it("says what the server refused, and keeps the form", async () => {
    serve(off, () => new Error("That isn't a Logo.dev publishable key"));
    render(LogosSection);
    await userEvent.type(await screen.findByLabelText("Publishable key"), "sk_wrong");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That isn't a Logo.dev publishable key");
  });

  it("offers to try again when the settings can't be read", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Server down"));
    render(LogosSection);
    expect(await screen.findByRole("status")).toHaveTextContent("Server down");
    serve(off);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Publishable key")).toBeInTheDocument();
  });
});
