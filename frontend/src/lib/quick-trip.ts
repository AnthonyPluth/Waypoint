import type { TripBody } from "./api-types";

export const TRIP_NAME_LIMIT = 100;

export type TripDraft = { name: string; start: string; end: string };

export type TripIssue = { field: "name" | "start" | "end"; message: string };

const DAY = /^\d{4}-\d\d-\d\d$/;

export const blankTrip = (): TripDraft => ({ name: "", start: "", end: "" });

export function tripIssues(d: TripDraft): TripIssue[] {
  const found: TripIssue[] = [];
  const name = d.name.trim();
  if (!name) found.push({ field: "name", message: "Enter where you’re going, or a name for the trip" });
  else if (name.length > TRIP_NAME_LIMIT) found.push({ field: "name", message: `The name can be at most ${TRIP_NAME_LIMIT} characters` });
  const start = DAY.test(d.start), end = DAY.test(d.end);
  if (d.start && !start) found.push({ field: "start", message: "Enter the first day as a date" });
  else if (!d.start && d.end) found.push({ field: "start", message: "Enter the first day, or clear the last day" });
  if (d.end && !end) found.push({ field: "end", message: "Enter the last day as a date" });
  else if (start && end && d.end < d.start) found.push({ field: "end", message: "The last day can’t be before the first" });
  return found;
}

export function tripBody(d: TripDraft, me: number | null): TripBody {
  const dates = d.start ? { start_date: d.start, end_date: d.end || d.start } : {};
  return { name: d.name.trim(), ...dates, ...(me === null ? {} : { people: [me] }) };
}
