// What counts as a phone, decided once. A phone gets every page and editor; this only picks the layout (the tab bar,
// bottom sheets, stacked rows). The same query is the `phone:` and `desktop:` variants in app.css, so CSS and code always agree. A phone turned sideways still counts:
// it's wide, but short and touch-driven.
export const PHONE_QUERY = "(max-width: 767px), (max-height: 500px) and (pointer: coarse)";

const mq = typeof matchMedia === "function" ? matchMedia(PHONE_QUERY) : null;

/** Live and reactive: `viewport.phone` is true while the screen is a phone's. */
export const viewport = $state({ phone: mq?.matches ?? false });
mq?.addEventListener("change", (e) => { viewport.phone = e.matches; });

/** True on a phone, in either orientation. */
export const isPhone = (): boolean => viewport.phone;
