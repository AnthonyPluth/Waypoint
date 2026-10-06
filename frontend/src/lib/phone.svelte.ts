export const PHONE_QUERY = "(max-width: 767px), (max-height: 500px) and (pointer: coarse)";

const mq = typeof matchMedia === "function" ? matchMedia(PHONE_QUERY) : null;

export const viewport = $state({ phone: mq?.matches ?? false });
mq?.addEventListener("change", (e) => { viewport.phone = e.matches; });

export const isPhone = (): boolean => viewport.phone;
