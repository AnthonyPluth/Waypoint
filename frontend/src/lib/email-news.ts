import type { Segment } from "$lib/api-types";

type EmailUpdate = NonNullable<Segment["email_update"]>;
type Field = EmailUpdate["updated"][number];

const NAMES: Record<Field, string> = {
  start_local: "the start",
  start_zone: "the start",
  end_local: "the end",
  end_zone: "the end",
  origin: "the first place",
  destination: "the last place",
};

function named(fields: Field[]): string {
  const names = [...new Set(fields.map((f) => NAMES[f]))];
  return names.length < 2 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function emailNews(update: EmailUpdate): { updated: string; disagreed: string } {
  return { updated: named(update.updated), disagreed: named(update.disagreed) };
}
