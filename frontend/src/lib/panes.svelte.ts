export const TWO_PANES_QUERY = "(min-width: 1024px)";
export const SETTLE_MS = 100;

const mq = typeof matchMedia === "function" ? matchMedia(TWO_PANES_QUERY) : null;

export const panes = $state({ two: mq?.matches ?? false });

let settling: ReturnType<typeof setTimeout> | undefined;
mq?.addEventListener("change", () => {
  clearTimeout(settling);
  settling = setTimeout(() => { panes.two = mq.matches; }, SETTLE_MS);
});
