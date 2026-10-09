export const TWO_PANES_QUERY = "(min-width: 1024px)";

const mq = typeof matchMedia === "function" ? matchMedia(TWO_PANES_QUERY) : null;

export const panes = $state({ two: mq?.matches ?? false });
mq?.addEventListener("change", (e) => { panes.two = e.matches; });
