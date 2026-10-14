export function freezeDemoClock(asOf: string): void {
  const epoch = Date.parse(`${asOf}T12:00:00Z`);
  if (!Number.isFinite(epoch)) throw new Error("Invalid demo snapshot date");
  const SystemDate = Date;
  globalThis.Date = new Proxy(SystemDate, {
    construct(target, args, newTarget) {
      return Reflect.construct(target, args.length ? args : [epoch], newTarget);
    },
    apply() {
      return new SystemDate(epoch).toString();
    },
    get(target, property, receiver) {
      return property === "now" ? () => epoch : Reflect.get(target, property, receiver);
    },
  });
}
