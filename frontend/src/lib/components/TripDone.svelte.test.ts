// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$lib/api", () => ({ api: vi.fn(), newPage: vi.fn(), signInUrl: () => "/auth/login" }));
vi.mock("svelte-sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { toast } from "svelte-sonner";
import { api } from "$lib/api";
import { segment, trip } from "../../test/fixtures";
import TripDone from "./TripDone.svelte";

const eligible = trip([segment({ id: 1 })], { emails: 2, can_clear_emails: true });

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(toast.error).mockReset();
});

describe("TripDone", () => {
  it("shows nothing for a trip that is not eligible", () => {
    render(TripDone, { trip: trip([segment({ id: 1 })], { emails: 2, can_clear_emails: false }), ondone: vi.fn() });
    expect(screen.queryByRole("button", { name: /remove the emails/i })).toBeNull();
  });

  it("shows nothing once there is nothing to remove", () => {
    render(TripDone, { trip: trip([segment({ id: 1 })], { emails: 0, can_clear_emails: false }), ondone: vi.fn() });
    expect(screen.queryByRole("region", { name: "Done with this trip" })).toBeNull();
  });

  it("asks in plain words first and does nothing on Cancel", async () => {
    const user = userEvent.setup();
    render(TripDone, { trip: eligible, ondone: vi.fn() });
    await user.click(screen.getByRole("button", { name: /remove the emails/i }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("The saved emails for this trip will be deleted. The bookings stay. This can’t be undone.");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api).not.toHaveBeenCalled();
  });

  it("removes the emails on confirm, says how many, and tells the page", async () => {
    const user = userEvent.setup();
    const ondone = vi.fn();
    vi.mocked(api).mockResolvedValue({ removed: 2 } as never);
    render(TripDone, { trip: eligible, ondone });
    await user.click(screen.getByRole("button", { name: /remove the emails/i }));
    await user.click(await screen.findByRole("button", { name: "Remove emails" }));
    await waitFor(() => expect(ondone).toHaveBeenCalledOnce());
    expect(api).toHaveBeenCalledWith("/api/trips/1/emails/clear", { method: "POST" });
    expect(toast.success).toHaveBeenCalledWith("Removed 2 saved emails");
  });

  it("says so in the singular", async () => {
    const user = userEvent.setup();
    vi.mocked(api).mockResolvedValue({ removed: 1 } as never);
    render(TripDone, { trip: trip([segment({ id: 1 })], { emails: 1, can_clear_emails: true }), ondone: vi.fn() });
    await user.click(screen.getByRole("button", { name: /remove the emails/i }));
    await user.click(await screen.findByRole("button", { name: "Remove emails" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Removed 1 saved email"));
  });

  it("keeps the dialog open and shows the error when it fails", async () => {
    const user = userEvent.setup();
    const ondone = vi.fn();
    vi.mocked(api).mockRejectedValue(new Error("The saved emails can be removed once a trip has ended at least 7 days ago"));
    render(TripDone, { trip: eligible, ondone });
    await user.click(screen.getByRole("button", { name: /remove the emails/i }));
    await user.click(await screen.findByRole("button", { name: "Remove emails" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("The saved emails can be removed once a trip has ended at least 7 days ago"));
    expect(ondone).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
