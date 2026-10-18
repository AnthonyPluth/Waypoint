export const urlsOf = (text) => String(text ?? "").split(",").map((u) => u.trim()).filter(Boolean);

export function planVisits({ pages, flows, viewports, ownPages, filtered, flowsOnly = false }) {
  const visits = [];
  if (!flowsOnly) for (const name of pages) for (const viewport of viewports) visits.push({ kind: "page", name, viewport });
  for (const flow of flows) {
    if (filtered && !flowsOnly && !pages.includes(flow.page ?? "upcoming")) continue;
    for (const viewport of flow.viewports ?? viewports) visits.push({ kind: "flow", flow, viewport });
  }
  if (!filtered) for (const name of pages.filter((n) => !ownPages.includes(n))) visits.push({ kind: "reduced", name, viewport: "phone" });
  return visits.map((visit, index) => ({ ...visit, index }));
}

export const labelOf = (visit) => (visit.kind === "flow" ? `flow ${visit.flow.name}` : visit.kind === "reduced" ? `reduced motion ${visit.name}` : visit.name);

export function splitVisits(visits, workers) {
  const shared = visits.filter((v) => v.kind !== "flow");
  const flows = new Map();
  for (const v of visits.filter((x) => x.kind === "flow")) flows.set(v.flow.name, [...(flows.get(v.flow.name) ?? []), v]);
  const queues = Array.from({ length: workers }, () => ({ load: 0, visits: [] }));
  const byCost = [...flows.values()].map((group) => ({ group, cost: group.length * (1 + group[0].flow.steps.length) }))
    .sort((a, b) => b.cost - a.cost || a.group[0].index - b.group[0].index);
  for (const { group, cost } of byCost) {
    const queue = queues.reduce((least, q) => (q.load < least.load ? q : least));
    queue.load += cost;
    queue.visits.push(...group);
  }
  return { shared, queues: queues.map((q) => q.visits.sort((a, b) => a.index - b.index)) };
}

const firstLine = (e) => String(e?.message ?? e).split("\n")[0];

export function notRun(visit, reason) {
  return { visit, screenshots: [], consoleErrors: [], problems: [`${labelOf(visit)} @ ${visit.viewport}: not run, ${reason}`], notes: [], worker: null };
}

export async function runPool({ visits, workers, prepare, work, release = async () => {} }) {
  const { shared, queues } = splitVisits(visits, workers);
  const pending = [...shared];
  const outcomes = [];
  const failures = [];
  await Promise.all(queues.map(async (queue, worker) => {
    let context;
    try { context = await prepare(worker); }
    catch (e) {
      failures.push({ worker, reason: firstLine(e) });
      for (const visit of queue) outcomes.push(notRun(visit, `worker ${worker + 1} could not start (${firstLine(e)})`));
      return;
    }
    try {
      for (let visit = pending.shift(); visit; visit = pending.shift()) outcomes.push({ ...(await work(visit, context, worker)), visit, worker });
      for (const visit of queue) outcomes.push({ ...(await work(visit, context, worker)), visit, worker });
    } catch (e) {
      failures.push({ worker, reason: firstLine(e) });
      const done = new Set(outcomes.map((o) => o.visit.index));
      for (const visit of queue.filter((v) => !done.has(v.index))) outcomes.push(notRun(visit, `worker ${worker + 1} stopped (${firstLine(e)})`));
    } finally {
      await release(context, worker).catch((e) => failures.push({ worker, reason: `closing: ${firstLine(e)}` }));
    }
  }));
  const done = new Set(outcomes.map((o) => o.visit.index));
  for (const visit of visits.filter((v) => !done.has(v.index))) outcomes.push(notRun(visit, "no worker could take it"));
  return { outcomes: outcomes.sort((a, b) => a.visit.index - b.visit.index), failures: failures.sort((a, b) => a.worker - b.worker) };
}

export function summarize({ outcomes, failures, startup = [], urls }) {
  const where = (worker) => (urls.length > 1 ? ` (instance ${worker + 1})` : "");
  const problems = [
    ...startup.map((s) => `${s.reason}${where(s.worker)}`),
    ...failures.map((f) => `worker ${f.worker + 1} failed: ${f.reason}`),
    ...outcomes.flatMap((o) => o.problems),
  ];
  const notes = outcomes.flatMap((o) => o.notes);
  const results = outcomes.map((o) => ({ label: labelOf(o.visit), viewport: o.visit.viewport, worker: o.worker, screenshots: o.screenshots, consoleErrors: o.consoleErrors }));
  return { problems, notes, results };
}
