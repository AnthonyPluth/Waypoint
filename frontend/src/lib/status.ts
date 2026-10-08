import type { FlightStatus, Segment } from "./api-types";

export type Tone = "ok" | "warn" | "bad" | "info" | "quiet";
export type Chip = { label: string; tone: Tone };

const BOOKING: Record<Segment["status"], Chip> = {
  confirmed: { label: "Confirmed", tone: "ok" },
  changed: { label: "Changed", tone: "warn" },
  cancelled: { label: "Cancelled", tone: "bad" },
};

const LIVE: Record<FlightStatus["state"], Chip> = {
  scheduled: { label: "On time", tone: "info" },
  delayed: { label: "Delayed", tone: "warn" },
  departed: { label: "Departed", tone: "info" },
  landed: { label: "Landed", tone: "quiet" },
  cancelled: { label: "Cancelled", tone: "bad" },
  diverted: { label: "Diverted", tone: "bad" },
};

export const bookingChip = (status: Segment["status"]): Chip => BOOKING[status];

export function liveChip(s: Pick<FlightStatus, "state" | "delay_minutes">): Chip {
  const chip = LIVE[s.state];
  return s.state === "delayed" && s.delay_minutes ? { ...chip, label: `Delayed ${s.delay_minutes} min` } : chip;
}

export function segmentChips(
  status: Segment["status"],
  flight: Pick<FlightStatus, "state" | "delay_minutes"> | null | undefined,
  liveOn: boolean,
): { booking: Chip; live: Chip | null } {
  return { booking: bookingChip(status), live: liveOn && flight ? liveChip(flight) : null };
}
