export type Limited = <T>(task: () => Promise<T>, stale?: () => boolean) => Promise<T | undefined>;

export function limited(max: number): Limited {
  let running = 0;
  const waiting: (() => void)[] = [];
  const next = () => {
    while (running < max && waiting.length) {
      running++;
      waiting.shift()!();
    }
  };
  return (task, stale) => new Promise((resolve, reject) => {
    waiting.push(() => {
      if (stale?.()) { running--; resolve(undefined); next(); return; }
      task().then(resolve, reject).finally(() => { running--; next(); });
    });
    next();
  });
}
