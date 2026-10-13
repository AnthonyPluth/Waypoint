import { screen } from "@testing-library/svelte";
import type { UserEvent } from "@testing-library/user-event";

export async function pickFromMenu(u: Pick<UserEvent, "click">, trigger: string | RegExp, item: string | RegExp) {
  await u.click(await screen.findByRole("button", { name: trigger }));
  await u.click(await screen.findByRole("button", { name: item }));
}

export const tripOptions = (u: Pick<UserEvent, "click">, item: "Delete trip" | "Merge another trip") => pickFromMenu(u, "Trip options", item);

export const bookingOptions = (u: Pick<UserEvent, "click">, item: string | RegExp) =>
  pickFromMenu(u, typeof item === "string" ? item.replace(/^(Move|Remove) /, "More options for ") : /^More options for/, item);
