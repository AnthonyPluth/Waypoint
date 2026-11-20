import { screen, waitFor } from "@testing-library/svelte";
import type { UserEvent } from "@testing-library/user-event";

export async function pickFromMenu(u: Pick<UserEvent, "click">, trigger: string | RegExp, item: string | RegExp) {
  await u.click(await screen.findByRole("button", { name: trigger }));
  await u.click(await screen.findByRole("button", { name: item }));
}

export const tripOptions = (u: Pick<UserEvent, "click">, item: "Delete trip" | "Merge another trip") => pickFromMenu(u, "Trip options", item);

export async function openBooking(u: Pick<UserEvent, "click">, name: string | RegExp): Promise<HTMLElement | null> {
  await screen.findByRole("list", { name: "Bookings" });
  const card = (await screen.findAllByRole("button")).find((b) => b.hasAttribute("data-booking") && (typeof name === "string" ? b.textContent?.includes(name) : name.test(b.textContent ?? "")));
  if (!card) return null;
  await u.click(card);
  return screen.findByRole("dialog");
}

export async function bookingOptions(u: Pick<UserEvent, "click">, item: string | RegExp) {
  const booking = typeof item === "string" ? item.replace(/^(Move|Remove) /, "") : "";
  if (booking && !screen.queryByRole("dialog")) await openBooking(u, booking);
  await pickFromMenu(u, typeof item === "string" ? item.replace(/^(Move|Remove) /, "More options for ") : /^More options for/, item);
}

export const topDialog = (): Promise<HTMLElement> => waitFor(() => {
  const asking = screen.getAllByRole("dialog").filter((d) => !d.querySelector("[data-testid='booking-detail']"));
  if (!asking.length) throw new Error("No dialog is open");
  return asking.at(-1)!;
});
