import { screen, waitFor, within } from "@testing-library/svelte";
import { expect } from "vitest";
import type { UserEvent } from "@testing-library/user-event";

export async function pickFromMenu(u: Pick<UserEvent, "click">, trigger: string | RegExp, item: string | RegExp) {
  await u.click(await screen.findByRole("button", { name: trigger }));
  await u.click(await screen.findByRole("button", { name: item }));
}

export async function tripOptions(u: Pick<UserEvent, "click">, item: "People on this trip" | "Add a booking" | "Delete trip" | "Merge another trip") {
  await u.click(await screen.findByRole("button", { name: "Trip options" }));
  await u.click(await screen.findByRole("menuitem", { name: item }));
}

export async function openBooking(u: Pick<UserEvent, "click">, name: string | RegExp): Promise<HTMLElement | null> {
  await screen.findByTestId("trip-bookings");
  const textOf = (b: HTMLElement) => (b.hasAttribute("data-detail") ? (b.closest("[data-hero]")?.textContent ?? "") : (b.textContent ?? ""));
  const card = (await screen.findAllByRole("button")).find((b) => (b.hasAttribute("data-booking") || b.hasAttribute("data-detail")) && (typeof name === "string" ? textOf(b).includes(name) : name.test(textOf(b))));
  if (!card) return null;
  await u.click(card);
  if (!card.hasAttribute("aria-controls")) return screen.findByRole("dialog");
  const panel = card.getAttribute("aria-controls")!;
  return waitFor(() => {
    const found = document.getElementById(panel);
    if (!found || found.hidden) throw new Error("The booking did not expand");
    return found;
  });
}

export async function closeBooking(u: Pick<UserEvent, "click">, detail: HTMLElement) {
  if (detail.getAttribute("role") === "dialog") {
    await u.click(within(detail).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.body.style.pointerEvents = "";
    return;
  }
  const button = document.querySelector<HTMLElement>(`[aria-controls="${detail.id}"]`)!;
  await u.click(button);
  await waitFor(() => expect(button).toHaveAttribute("aria-expanded", "false"));
}

export async function bookingOptions(u: Pick<UserEvent, "click">, item: string | RegExp) {
  const booking = typeof item === "string" ? item.replace(/^(Move|Remove) /, "") : "";
  if (booking && !screen.queryByRole("button", { name: `More options for ${booking}` })) await openBooking(u, booking);
  await pickFromMenu(u, typeof item === "string" ? item.replace(/^(Move|Remove) /, "More options for ") : /^More options for/, item);
}

export const topDialog = (): Promise<HTMLElement> => waitFor(() => {
  const asking = screen.getAllByRole("dialog").filter((d) => !d.querySelector("[data-testid='booking-detail']"));
  if (!asking.length) throw new Error("No dialog is open");
  return asking.at(-1)!;
});
