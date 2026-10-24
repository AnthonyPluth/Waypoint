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

const off: AiSettings = { mode: "off", ollama_url: "", ollama_model: "", openrouter_model: "", key: null, auto: false };

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

  it("offers reading unreadable mail automatically only while the AI is on, warns when it is chosen, and saves it", async () => {
    serve(off, (b) => ({ ...off, mode: b.mode, ollama_url: b.ollama_url, ollama_model: b.ollama_model, auto: b.auto }) as unknown as AiSettings);
    render(AiSection);
    await screen.findByRole("radio", { name: /Off/ });
    expect(screen.queryByRole("checkbox", { name: /automatically/ })).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: /Local/ }));
    const box = screen.getByRole("checkbox", { name: /Read unreadable mail with AI automatically/ });
    expect(box).not.toBeChecked();
    expect(screen.queryByText(/without asking each time/)).toBeNull();
    await userEvent.click(box);
    expect(screen.getByRole("note")).toHaveTextContent("Waypoint will send the text of travel emails it couldn’t read to the AI you chose, and of emails it did read when a booking is missing a detail, without asking each time.");
    await userEvent.type(screen.getByLabelText("Ollama address"), "http://ollama.example:11434");
    await userEvent.type(screen.getByLabelText("Model"), "llama3.1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI settings saved"));
    expect(vi.mocked(api).mock.calls.at(-1)?.[1]).toMatchObject({ body: { mode: "local", auto: true } });
    expect(screen.getByRole("checkbox", { name: /automatically/ })).toBeChecked();
  });

  it("does not send the automatic choice on when the AI is turned off", async () => {
    serve({ ...off, mode: "local", ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1", auto: true });
    render(AiSection);
    expect(await screen.findByRole("checkbox", { name: /automatically/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /Off/ }));
    expect(screen.queryByRole("checkbox", { name: /automatically/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI is off"));
    expect(vi.mocked(api).mock.calls.at(-1)?.[1]).toMatchObject({ body: { mode: "off", auto: false } });
  });

  it("saves a local server and model", async () => {
    serve(off);
    render(AiSection);
    await userEvent.click(await screen.findByRole("radio", { name: /Local/ }));
    await userEvent.type(screen.getByLabelText("Ollama address"), "http://ollama.example:11434");
    await userEvent.type(screen.getByLabelText("Model"), "llama3.1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI settings saved"));
    expect(api).toHaveBeenCalledWith("/api/ai", { method: "POST", body: { mode: "local", ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1", openrouter_model: "", auto: false } });
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

  it("says email is read only by a local AI when OpenRouter is chosen, and offers no automatic reading", async () => {
    serve({ ...off, mode: "openrouter", openrouter_model: "some/model", key: "saved" });
    render(AiSection);
    expect(await screen.findByRole("note")).toHaveTextContent("Reading email with AI needs Local (Ollama). OpenRouter is used only for trip destinations");
    expect(screen.queryByRole("checkbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(api).mock.calls.at(-1)?.[1]).toMatchObject({ body: { mode: "openrouter", auto: false } });
  });

  it("offers automatic reading with a local AI only", async () => {
    serve({ ...off, mode: "local", ollama_url: "http://ollama.example:11434", ollama_model: "llama3.1" });
    render(AiSection);
    await userEvent.click(await screen.findByRole("checkbox", { name: /Read unreadable mail with AI automatically/ }));
    expect(screen.getByRole("note")).toHaveTextContent("Waypoint will send the text of travel emails");
    await userEvent.click(screen.getByRole("radio", { name: /OpenRouter/ }));
    expect(screen.queryByRole("checkbox")).toBeNull();
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
