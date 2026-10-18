import { describe, expect, it } from "vitest";
import { labelOf, notRun, planVisits, runPool, splitVisits, summarize, urlsOf } from "./jobs.mjs";

const flow = (name, steps = 3, extra = {}) => ({ name, steps: Array.from({ length: steps }, () => ({ click: "a" })), ...extra });
const plan = (flows, extra = {}) => planVisits({ pages: ["upcoming", "trips", "oauth-approve"], flows, viewports: ["phone", "desktop"], ownPages: ["oauth-approve"], filtered: false, ...extra });
const names = (visits) => visits.map((v) => `${labelOf(v)} @ ${v.viewport}`);

describe("urlsOf", () => {
  it("splits a list of addresses and drops blanks", () => {
    expect(urlsOf(" http://a:1, http://b:2,,")).toEqual(["http://a:1", "http://b:2"]);
    expect(urlsOf(undefined)).toEqual([]);
  });
});

describe("planVisits", () => {
  it("lists each page at each width, then each flow at its widths, then reduced motion on the phone, in that order", () => {
    const visits = plan([flow("a"), flow("b", 2, { viewports: ["laptop"] })]);
    expect(names(visits)).toEqual([
      "upcoming @ phone", "upcoming @ desktop", "trips @ phone", "trips @ desktop", "oauth-approve @ phone", "oauth-approve @ desktop",
      "flow a @ phone", "flow a @ desktop", "flow b @ laptop", "reduced motion upcoming @ phone", "reduced motion trips @ phone",
    ]);
    expect(visits.map((v) => v.index)).toEqual(visits.map((_, i) => i));
  });

  it("visits only the asked pages and the flows that start on them, with no reduced-motion pass", () => {
    const visits = planVisits({ pages: ["trips"], flows: [flow("a", 3, { page: "trips" }), flow("b")], viewports: ["phone"], ownPages: [], filtered: true });
    expect(names(visits)).toEqual(["trips @ phone", "flow a @ phone"]);
  });

  it("runs only the named flows when asked for flows alone", () => {
    const visits = planVisits({ pages: ["upcoming"], flows: [flow("a", 3, { page: "trips" })], viewports: ["phone", "desktop"], ownPages: [], filtered: true, flowsOnly: true });
    expect(names(visits)).toEqual(["flow a @ phone", "flow a @ desktop"]);
  });
});

describe("splitVisits", () => {
  const flows = [flow("a", 9), flow("b", 2), flow("c", 5), flow("d", 3), flow("e", 1)];
  const visits = plan(flows);

  it("keeps every page and reduced-motion visit in the shared list", () => {
    const { shared } = splitVisits(visits, 3);
    expect(shared.every((v) => v.kind !== "flow")).toBe(true);
    expect(shared).toHaveLength(visits.filter((v) => v.kind !== "flow").length);
  });

  it("gives every flow to exactly one queue, with all its widths together and in the serial order", () => {
    const { queues } = splitVisits(visits, 3);
    const seen = queues.flatMap((q) => q.map((v) => v.index));
    expect(seen.sort((a, b) => a - b)).toEqual(visits.filter((v) => v.kind === "flow").map((v) => v.index));
    for (const queue of queues) {
      expect(queue.map((v) => v.index)).toEqual([...queue.map((v) => v.index)].sort((a, b) => a - b));
      for (const v of queue) expect(queue.filter((x) => x.flow.name === v.flow.name)).toHaveLength(2);
    }
  });

  it("balances the queues by cost and splits the same way every time", () => {
    const first = splitVisits(visits, 3).queues.map((q) => names(q));
    expect(splitVisits(visits, 3).queues.map((q) => names(q))).toEqual(first);
    const loads = splitVisits(visits, 3).queues.map((q) => q.reduce((n, v) => n + 1 + v.flow.steps.length, 0));
    expect(Math.max(...loads) - Math.min(...loads)).toBeLessThanOrEqual(10);
    expect(first[0]).toContain("flow a @ phone");
  });

  it("puts every flow in one queue, in order, for one worker", () => {
    const { queues } = splitVisits(visits, 1);
    expect(queues).toHaveLength(1);
    expect(names(queues[0])).toEqual(names(visits.filter((v) => v.kind === "flow")));
  });

  it("leaves a queue empty when there are more workers than flows", () => {
    const { queues } = splitVisits(plan([flow("a")]), 3);
    expect(queues.map((q) => q.length)).toEqual([2, 0, 0]);
  });
});

describe("runPool", () => {
  const visits = plan([flow("a", 5), flow("b", 4), flow("c", 3)]);
  const ok = (v, env, worker) => ({ screenshots: [], consoleErrors: [], problems: [], notes: [], ranOn: `${env.name}/${worker}` });

  it("visits every page once, before any flow on that worker's server, and each flow only on its own", async () => {
    const log = [];
    const { outcomes, failures } = await runPool({
      visits, workers: 2,
      prepare: async (worker) => ({ name: `s${worker}` }),
      work: async (v, env, worker) => { log.push({ worker, kind: v.kind, label: labelOf(v), viewport: v.viewport }); await new Promise((r) => setTimeout(r, v.kind === "page" ? 1 : 0)); return ok(v, env, worker); },
    });
    expect(failures).toEqual([]);
    expect(outcomes.map((o) => o.visit.index)).toEqual(visits.map((v) => v.index));
    expect(log).toHaveLength(visits.length);
    for (const worker of [0, 1]) {
      const mine = log.filter((l) => l.worker === worker);
      const firstFlow = mine.findIndex((l) => l.kind === "flow");
      expect(mine.slice(firstFlow < 0 ? mine.length : firstFlow).every((l) => l.kind === "flow")).toBe(true);
    }
    const flowWorkers = new Map();
    for (const l of log.filter((x) => x.kind === "flow")) flowWorkers.set(l.label, new Set([...(flowWorkers.get(l.label) ?? []), l.worker]));
    expect([...flowWorkers.values()].every((w) => w.size === 1)).toBe(true);
  });

  it("with one worker visits the pages and reduced-motion passes first, then the flows, each in the order of the plan", async () => {
    const seen = [];
    await runPool({ visits, workers: 1, prepare: async () => ({ name: "only" }), work: async (v, env) => { seen.push(v.index); return ok(v, env, 0); } });
    expect(seen).toEqual([...visits.filter((v) => v.kind !== "flow"), ...visits.filter((v) => v.kind === "flow")].map((v) => v.index));
  });

  it("reports a worker that cannot start, runs its pages elsewhere, and does not hide the others", async () => {
    const { outcomes, failures } = await runPool({
      visits, workers: 2,
      prepare: async (worker) => { if (worker === 0) throw new Error("browser missing\nstack"); return { name: "s1" }; },
      work: async (v, env, worker) => ok(v, env, worker),
    });
    expect(failures).toEqual([{ worker: 0, reason: "browser missing" }]);
    const lost = outcomes.filter((o) => o.problems.length);
    expect(lost.length).toBeGreaterThan(0);
    expect(lost.every((o) => o.problems[0].includes("not run, worker 1 could not start (browser missing)"))).toBe(true);
    expect(outcomes.filter((o) => !o.problems.length).every((o) => o.worker === 1)).toBe(true);
    expect(outcomes).toHaveLength(visits.length);
  });

  it("marks what a stopped worker left undone and lets the other worker finish", async () => {
    const { outcomes, failures } = await runPool({
      visits, workers: 2,
      prepare: async (worker) => ({ name: `s${worker}` }),
      work: async (v, env, worker) => { if (worker === 0 && v.kind === "flow") throw new Error("server gone"); return ok(v, env, worker); },
    });
    expect(failures).toEqual([{ worker: 0, reason: "server gone" }]);
    expect(outcomes).toHaveLength(visits.length);
    const stopped = outcomes.filter((o) => o.problems.some((p) => p.includes("worker 1 stopped (server gone)")));
    expect(stopped.length).toBeGreaterThan(0);
    expect(outcomes.filter((o) => o.worker === 1 && o.problems.length)).toEqual([]);
  });

  it("flags every visit when no worker can start", async () => {
    const { outcomes, failures } = await runPool({ visits, workers: 2, prepare: async () => { throw new Error("no browser"); }, work: ok });
    expect(failures).toHaveLength(2);
    expect(outcomes).toHaveLength(visits.length);
    expect(outcomes.every((o) => o.problems.length === 1)).toBe(true);
    expect(outcomes.filter((o) => o.problems[0].includes("no worker could take it")).length).toBe(visits.filter((v) => v.kind !== "flow").length);
  });

  it("releases every worker's browser, and says when closing fails", async () => {
    const released = [];
    const { failures } = await runPool({
      visits, workers: 2, prepare: async (worker) => ({ name: `s${worker}` }), work: async (v, env, worker) => ok(v, env, worker),
      release: async (env, worker) => { released.push(worker); if (worker === 1) throw new Error("already closed"); },
    });
    expect(released.sort()).toEqual([0, 1]);
    expect(failures).toEqual([{ worker: 1, reason: "closing: already closed" }]);
  });
});

describe("summarize", () => {
  const visits = plan([flow("a")]);
  const outcome = (v, problems = [], notes = [], worker = 0) => ({ visit: v, worker, screenshots: ["x.png"], consoleErrors: [], problems, notes });

  it("lists problems and notes in the order of the plan whichever worker found them", () => {
    const outcomes = [outcome(visits[0], [], ["note 1"], 1), outcome(visits[1], ["upcoming @ desktop: a11y color-contrast"], [], 0), outcome(visits.at(-1), ["reduced motion trips @ phone: animations still run"], ["note 2"], 1)];
    const { problems, notes, results } = summarize({ outcomes, failures: [], urls: ["http://a", "http://b"] });
    expect(problems).toEqual(["upcoming @ desktop: a11y color-contrast", "reduced motion trips @ phone: animations still run"]);
    expect(notes).toEqual(["note 1", "note 2"]);
    expect(results.map((r) => [r.label, r.viewport, r.worker])).toEqual([["upcoming", "phone", 1], ["upcoming", "desktop", 0], ["reduced motion trips", "phone", 1]]);
  });

  it("puts a seeding failure and a failed worker first, naming the server only when there are several", () => {
    const outcomes = [outcome(visits[0], ["upcoming @ phone: boom"])];
    const one = summarize({ outcomes, failures: [], startup: [{ worker: 0, reason: "seeding the demo assistants: no token" }], urls: ["http://a"] });
    expect(one.problems).toEqual(["seeding the demo assistants: no token", "upcoming @ phone: boom"]);
    const many = summarize({ outcomes, failures: [{ worker: 1, reason: "server gone" }], startup: [{ worker: 1, reason: "seeding the demo assistants: no token" }], urls: ["http://a", "http://b"] });
    expect(many.problems).toEqual(["seeding the demo assistants: no token (instance 2)", "worker 2 failed: server gone", "upcoming @ phone: boom"]);
  });

  it("says why a visit did not run, with its page, width and flow", () => {
    const flowVisit = plan([flow("a")]).find((v) => v.kind === "flow");
    expect(notRun(flowVisit, "worker 2 stopped (x)").problems).toEqual(["flow a @ phone: not run, worker 2 stopped (x)"]);
  });
});
