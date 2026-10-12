import type { Trip } from "./api-types";

export const MAX_MINOR = 1_000_000_000;

const places = (currency: string): number => {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
};

export function formatMoney(minor: number, currency: string): string {
  const d = places(currency);
  const amount = minor / 10 ** d;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount.toFixed(d)} ${currency}`;
  }
}

export const formatTotals = (totals: Trip["costs"]["totals"]): string => totals.map((t) => formatMoney(t.amount_minor, t.currency)).join(" + ");

export const countNote = (costs: Trip["costs"]): string | null =>
  costs.priced < costs.bookings ? `${costs.priced} of ${costs.bookings} ${costs.bookings === 1 ? "booking" : "bookings"}` : null;

export const amountText = (minor: number, currency: string): string => {
  const d = places(currency);
  return (minor / 10 ** d).toFixed(d);
};

export function toMinor(text: string, currency: string): number | null {
  const d = places(currency);
  if (/[-−()]/.test(text)) return null;
  const t = text.replace(/[\s']/g, "").replace(/^[^\d]+|[^\d]+$/g, "");
  if (!/^\d[\d.,]*$/.test(t)) return null;
  const last = Math.max(t.lastIndexOf("."), t.lastIndexOf(","));
  let whole = t;
  let fraction = "";
  if (last >= 0) {
    const head = t.slice(0, last), tail = t.slice(last + 1), sep = t[last], other = sep === "." ? "," : ".";
    const grouped = (text: string, mark: string) => text.split(mark).every((part, i) => (i === 0 ? /^\d{1,3}$/ : /^\d{3}$/).test(part));
    if (head.includes(other)) {
      if (!grouped(head, other)) return null;
      whole = head.replaceAll(other, "");
      fraction = tail;
    } else if (head.includes(sep)) {
      if (!grouped(t, sep)) return null;
      whole = t.replaceAll(sep, "");
    } else if (tail.length === 3 && d !== 3) {
      if (!/^\d{1,3}$/.test(head)) return null;
      whole = head + tail;
    } else {
      whole = head;
      fraction = tail;
    }
  }
  if (!/^\d*$/.test(fraction) || fraction.length > d || whole === "") return null;
  const minor = Number(whole + fraction.padEnd(d, "0"));
  return Number.isSafeInteger(minor) && minor <= MAX_MINOR ? minor : null;
}
