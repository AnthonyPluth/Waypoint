import { screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";

export async function chooseZone(field: HTMLElement, zone: string) {
  const user = userEvent.setup();
  await user.click(field);
  await user.clear(field);
  await user.type(field, zone);
  const option = screen.getAllByRole("option", { hidden: true }).find((candidate) => candidate.getAttribute("data-value") === zone);
  if (!option) throw new Error(`No option for ${zone}`);
  await user.click(option);
}
