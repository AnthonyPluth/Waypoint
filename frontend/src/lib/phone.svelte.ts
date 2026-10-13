export const PHONE_QUERY = "(max-width: 767px), (max-height: 500px) and (pointer: coarse)";

const mq = typeof matchMedia === "function" ? matchMedia(PHONE_QUERY) : null;

export const SPLIT_QUERY = "(min-width: 1100px)";

const wide = typeof matchMedia === "function" ? matchMedia(SPLIT_QUERY) : null;

export const viewport = $state({ phone: mq?.matches ?? false, split: wide?.matches ?? false });
mq?.addEventListener("change", (e) => { viewport.phone = e.matches; });
wide?.addEventListener("change", (e) => { viewport.split = e.matches; });

export const isPhone = (): boolean => viewport.phone;
