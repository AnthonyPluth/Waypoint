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

const empty: AiSettings = { ollama_url: "", ollama_model: "" };
const saved: AiSettings = { ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1" };

beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(toast.success).mockReset(); });

const serve = (current: AiSettings, post: (b: Record<string, string>) => AiSettings | Error = (b) => ({ ...current, ...b }) as AiSettings) =>
  vi.mocked(api).mockImplementation(async (_p: string, opts?: { method?: string; body?: unknown }) => {
    if (opts?.method !== "POST") return current as never;
    const r = post(opts.body as Record<string, string>);
    if (r instanceof Error) throw r;
    return r as never;
  });

describe("Settings → AI", () => {
  it("has only the Ollama address and the model: no mode, no key, no automatic reading", async () => {
    serve(empty);
    render(AiSection);
    expect(await screen.findByLabelText(/Ollama address/)).toHaveValue("");
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByLabelText(/key/i)).toBeNull();
    expect(screen.queryByText(/OpenRouter/)).toBeNull();
  });

  it("says plainly, with the address empty or saved, that a saved address sends the text of booking emails it couldn’t read fully to that server, on the household’s own server", async () => {
    serve(empty);
    render(AiSection);
    expect(await screen.findByRole("note")).toHaveTextContent("Once an address is saved, Waypoint sends the text of booking emails it couldn’t read fully to that server to fill the gaps. It stays on your household’s own server.");
    expect(screen.getByText(/Leave it empty to not use AI/)).toBeInTheDocument();
  });

  it("shows a saved address and model", async () => {
    serve(saved);
    render(AiSection);
    expect(await screen.findByLabelText(/Ollama address/)).toHaveValue("http://ollama.example:11434");
    expect(screen.getByLabelText("Model")).toHaveValue("llama3.1");
  });

  it("saves an address and a model", async () => {
    serve(empty);
    render(AiSection);
    await userEvent.type(await screen.findByLabelText(/Ollama address/), "http://ollama.example:11434");
    await userEvent.type(screen.getByLabelText("Model"), "llama3.1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI settings saved"));
    expect(api).toHaveBeenCalledWith("/api/ai", { method: "POST", body: { ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1" } });
  });

  it("turns AI off by saving the address empty", async () => {
    serve(saved, () => empty);
    render(AiSection);
    await userEvent.clear(await screen.findByLabelText(/Ollama address/));
    await userEvent.clear(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI is off"));
    expect(api).toHaveBeenCalledWith("/api/ai", { method: "POST", body: { ollama_url: "", ollama_model: "" } });
  });

  it("shows what the server refused and keeps the form", async () => {
    serve(empty, () => new Error("Enter the model to use with the Ollama address"));
    render(AiSection);
    await userEvent.type(await screen.findByLabelText(/Ollama address/), "http://ollama.example:11434");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the model to use with the Ollama address");
    expect(screen.getByLabelText(/Ollama address/)).toHaveValue("http://ollama.example:11434");
  });

  it("says when it can’t load, with Try again", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("Offline."));
    render(AiSection);
    expect(await screen.findByText("Offline.")).toBeInTheDocument();
    serve(empty);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText(/Ollama address/)).toBeInTheDocument();
  });
});
