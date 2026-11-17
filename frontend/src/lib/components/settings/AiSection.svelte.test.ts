// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { api } from "$lib/api";
import type { AiSettings } from "$lib/api-types";
import { toast } from "svelte-sonner";
import AiSection from "./AiSection.svelte";

const off: AiSettings = { mode: "off", ollama_url: "", ollama_model: "", openrouter_model: "", key: null };

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); });

const serve = (current: AiSettings, post: (b: Record<string, string>) => AiSettings | Error = (b) => ({ ...current, ...b }) as AiSettings) =>
  vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string; body?: unknown }) => {
    if (opts?.method !== "POST") return current as never;
    const r = post(opts.body as Record<string, string>);
    if (r instanceof Error) throw r;
    return r as never;
  });

describe("Settings → AI", () => {
  it("is off to begin with, and asks for nothing", async () => {
    serve(off);
    render(AiSection);
    expect(await screen.findByRole("radio", { name: /Off/ })).toBeChecked();
    expect(screen.queryByLabelText("Ollama address")).toBeNull();
    expect(screen.queryByLabelText("OpenRouter key")).toBeNull();
  });

  it("has no control for reading mail automatically: turning an AI mode on is the choice", async () => {
    serve(off);
    render(AiSection);
    await screen.findByRole("radio", { name: /Off/ });
    for (const mode of [/Local/, /OpenRouter/, /Off/]) {
      await userEvent.click(screen.getByRole("radio", { name: mode }));
      expect(screen.queryByRole("checkbox")).toBeNull();
      expect(screen.queryByText(/Read unreadable mail with AI automatically/)).toBeNull();
    }
  });

  it("says plainly with Local on that the text of booking emails it couldn’t read fully goes to the household’s own server", async () => {
    serve({ ...off, mode: "local", ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1" });
    render(AiSection);
    expect(await screen.findByRole("note")).toHaveTextContent("Waypoint sends the text of booking emails it couldn’t read fully to your Ollama server to fill the gaps. It stays on your household’s server and network.");
  });

  it("says plainly with OpenRouter on that the text of booking emails it couldn’t read fully goes to a hosted service", async () => {
    serve({ ...off, mode: "openrouter", openrouter_model: "some/model", key: "saved" });
    render(AiSection);
    expect(await screen.findByRole("note")).toHaveTextContent("Waypoint sends the text of booking emails it couldn’t read fully to OpenRouter, a hosted service outside your household, to fill the gaps. Email addresses and saved loyalty numbers are removed first.");
  });

  it("says nothing is sent while the AI is off", async () => {
    serve(off);
    render(AiSection);
    await screen.findByRole("radio", { name: /Off/ });
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByText("Email never goes to an AI, and nothing is sent for trip destinations.")).toBeInTheDocument();
  });

  it("saves a local server and model", async () => {
    serve(off);
    render(AiSection);
    await userEvent.click(await screen.findByRole("radio", { name: /Local/ }));
    await userEvent.type(screen.getByLabelText("Ollama address"), "http://ollama.example:11434");
    await userEvent.type(screen.getByLabelText("Model"), "llama3.1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI settings saved"));
    expect(api).toHaveBeenCalledWith("/api/ai", { method: "POST", body: { mode: "local", ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1", openrouter_model: "" } });
  });

  it("sends an OpenRouter key once and then never has it: it shows only that one is saved", async () => {
    serve(off, (b) => ({ ...off, mode: "openrouter", openrouter_model: b.openrouter_model, key: "saved" }));
    render(AiSection);
    await userEvent.click(await screen.findByRole("radio", { name: /OpenRouter/ }));
    await userEvent.type(screen.getByLabelText("Model"), "some/model");
    await userEvent.type(screen.getByLabelText("OpenRouter key"), "sk-or-test-1234");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(api).mock.calls.at(-1)?.[1]).toMatchObject({ body: { openrouter_key: "sk-or-test-1234" } });
    const field = screen.getByLabelText("OpenRouter key") as HTMLInputElement;
    expect(field.value).toBe("");
    expect(field.placeholder).toMatch(/Saved/);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.length).toBeGreaterThan(2));
    expect(JSON.stringify(vi.mocked(api).mock.calls.at(-1))).not.toContain("openrouter_key");
  });

  it("saves OpenRouter as the choice with nothing else to turn on", async () => {
    serve({ ...off, mode: "openrouter", openrouter_model: "some/model", key: "saved" });
    render(AiSection);
    await screen.findByRole("note");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(api).mock.calls.at(-1)?.[1]).toEqual({ method: "POST", body: { mode: "openrouter", ollama_url: "", ollama_model: "", openrouter_model: "some/model" } });
  });

  it("says where a key from the environment comes from, and offers no field for it", async () => {
    serve({ ...off, mode: "openrouter", openrouter_model: "some/model", key: "env" });
    render(AiSection);
    expect(await screen.findByText("OPENROUTER_API_KEY")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("sk-or-…")).toBeNull();
  });

  it("forgets a saved key", async () => {
    serve({ ...off, mode: "openrouter", openrouter_model: "some/model", key: "saved" }, () => off);
    render(AiSection);
    await userEvent.click(await screen.findByRole("button", { name: "Forget the saved key" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Key forgotten"));
    expect(api).toHaveBeenCalledWith("/api/ai", { method: "POST", body: { mode: "off", openrouter_key: "" } });
    expect(screen.queryByRole("button", { name: "Forget the saved key" })).toBeNull();
  });

  it("shows what the server refused and keeps the form", async () => {
    serve(off, () => new Error("Enter the Ollama address and the model to use"));
    render(AiSection);
    await userEvent.click(await screen.findByRole("radio", { name: /Local/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the Ollama address and the model to use");
    expect(screen.getByRole("radio", { name: /Local/ })).toBeChecked();
  });

  it("says when it can’t load, with Try again", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Offline."));
    render(AiSection);
    expect(await screen.findByText("Offline.")).toBeInTheDocument();
    serve(off);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("radio", { name: /Off/ })).toBeChecked();
  });
});
