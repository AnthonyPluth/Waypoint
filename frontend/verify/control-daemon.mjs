import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ACTING_COMMANDS, ARTIFACTS, UNREACHABLE_ARGS, ControlError, allowedRequest, isGuardedPath, LOOPBACK_HOSTS, PROG, ROOT, closest, errorResult, jsExpression, lastShotNumber, onHost, parseTarget, readState, rel, removeState, routeUrl, sameServer, scrubText, scrubUrl, shotName, socketPath, writeState } from "./control.mjs";
import { startServer } from "./control-server.mjs";
import { VIEWPORTS, checksAfter, contextOptions, launchOptions, prepareContext, readFlows, recheck, runStep, screenshotFile, setUpOffline, settlePage } from "./verify.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const BUFFER = 500;
const START_ROUTE = "#upcoming";
const EVAL_SETTLE_MS = 500;

const log = (line) => console.log(`${new Date().toISOString()} ${line}`);
const uniqueList = (items) => [...new Set(items)];
const firstLine = (e) => String(e?.message ?? e).split("\n")[0];

function options(argv) {
  const get = (name) => { const i = argv.indexOf(`--${name}`); return i < 0 ? undefined : argv[i + 1]; };
  return { dir: get("dir"), python: get("python"), now: get("now"), viewport: get("viewport") ?? "phone", idleMinutes: Number(get("idle-minutes") ?? 30) };
}

function runToEnd(program, args, env) {
  return new Promise((resolve, reject) => {
    const proc = spawn(program, args, { cwd: ROOT, env, stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    proc.stdout.on("data", (d) => { out += d; });
    proc.stderr.on("data", (d) => { out += d; });
    proc.on("error", reject);
    proc.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${args.slice(0, 3).join(" ")} exited with ${code}: ${out.trim().split("\n").slice(-3).join(" | ")}`))));
  });
}

async function main() {
  const opt = options(process.argv.slice(2));
  if (!opt.dir || !opt.dir.startsWith(`${ARTIFACTS}/`) || !opt.python || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(opt.now ?? "") || !(opt.viewport in VIEWPORTS)) {
    console.error("control-daemon: started without its options (tools/control start starts it)");
    process.exit(2);
  }
  const { dir } = opt;
  const sessionDir = join(dir, `session-${process.pid}`);
  const seedDir = join(sessionDir, "seed");
  const token = randomBytes(32).toString("hex");
  const socket = socketPath(dir);
  const state = { pid: process.pid, status: "starting", dir, sessionDir, socket, token, viewport: opt.viewport, idleMinutes: opt.idleMinutes, now: opt.now, startedAt: new Date().toISOString() };
  const save = (more = {}) => { Object.assign(state, more); writeState(state, dir); };
  save();

  let server = null, browser = null, listener = null, page = null, ctx = null, base = "", servers = 0, idle = null, ending = false;
  const consoleBuffer = [], requests = [], offsite = [], refused = [], blockedHosts = [];
  let acting = false;
  let shots = 0;

  async function shutdown(reason, code = 0, { keepState = false } = {}) {
    if (ending) return;
    ending = true;
    log(`stopping: ${reason}`);
    clearTimeout(idle);
    if (listener) await new Promise((r) => listener.close(() => r())).catch(() => null);
    rmSync(socket, { force: true });
    if (browser) await Promise.race([browser.close(), new Promise((r) => setTimeout(r, 10000))]).catch(() => null);
    if (server) await server.stop().catch((e) => log(`stopping the demo server: ${firstLine(e)}`));
    rmSync(sessionDir, { recursive: true, force: true });
    if (!keepState && readState(dir)?.pid === process.pid) removeState(dir);
    process.exit(code);
  }
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => shutdown(`signal ${sig}`));
  process.on("uncaughtException", (e) => { log(`uncaught: ${e.stack ?? e}`); shutdown("an internal error", 1); });
  process.on("unhandledRejection", (e) => { log(`unhandled: ${e?.stack ?? e}`); shutdown("an internal error", 1); });
  const touch = () => { clearTimeout(idle); idle = setTimeout(() => shutdown(`idle for ${opt.idleMinutes} minutes`), opt.idleMinutes * 60000); };

  async function newServer() {
    server = await startServer({
      command: (port, folder) => [opt.python, "-m", "waypoint.verify", "serve", "--parent", String(process.pid), "--seed", seedDir, "--data", folder, "--port", String(port)],
      folder: join(sessionDir, `data-${++servers}`), timeout: 60000, cwd: ROOT,
    });
    base = `http://127.0.0.1:${server.port}`;
  }

  function route() {
    try { const u = new URL(page.url()); return `${u.pathname}${u.hash}`; } catch { return page.url(); }
  }

  function host() {
    try { const h = new URL(page.url()).hostname; return LOOPBACK_HOSTS.includes(h) ? h : "127.0.0.1"; } catch { return "127.0.0.1"; }
  }

  const keep = (list, entry) => { list.push(entry); if (list.length > BUFFER) list.shift(); };

  const guardsWrites = (url) => allowedRequest(url.href, base) && isGuardedPath(url.pathname);
  const refuseWrites = (route) => {
    const request = route.request();
    if (["GET", "HEAD", "OPTIONS"].includes(request.method())) return route.fallback();
    refused.push(`${request.method()} ${scrubUrl(request.url(), base)}`);
    return route.abort("blockedbyclient");
  };
  let guarded = null;
  let blocking = null;
  let wantBlock = true;
  const offServer = (url) => !allowedRequest(url.href, base);
  const abortOffServer = (route) => {
    blockedHosts.push(scrubUrl(route.request().url(), base) ?? "a data address");
    return route.abort("blockedbyclient");
  };

  async function blockOffServer(on) {
    wantBlock = on;
    if (blocking && (!on || blocking !== ctx)) {
      await blocking.unroute(offServer, abortOffServer).catch(() => null);
      blocking = null;
    }
    if (on && !blocking && ctx) {
      await ctx.route(offServer, abortOffServer);
      blocking = ctx;
    }
  }

  async function guardWrites(on) {
    if (guarded && (!on || guarded !== ctx)) {
      await guarded.unroute(guardsWrites, refuseWrites).catch(() => null);
      guarded = null;
    }
    if (on && !guarded && ctx) {
      await ctx.route(guardsWrites, refuseWrites);
      guarded = ctx;
    }
  }

  async function openPage(viewport, phoneAgent = false) {
    const previous = ctx;
    const fresh = await browser.newContext(contextOptions(viewport, { phoneAgent }));
    await prepareContext(fresh, opt.now);
    if (wantBlock) {
      await fresh.route(offServer, abortOffServer);
      blocking = fresh;
    }
    const tab = await fresh.newPage();
    tab.setDefaultTimeout(30000);
    tab.setDefaultNavigationTimeout(30000);
    tab.on("console", (m) => keep(consoleBuffer, { type: m.type(), text: scrubText(firstLine(m.text())).slice(0, 300), route: route() }));
    tab.on("pageerror", (e) => keep(consoleBuffer, { type: "pageerror", text: scrubText(firstLine(e)).slice(0, 300), route: route() }));
    tab.on("response", (r) => { const path = scrubUrl(r.url(), base); if (path) keep(requests, { method: r.request().method(), path, status: r.status(), type: r.request().resourceType() }); });
    tab.on("requestfailed", (r) => {
      const path = scrubUrl(r.url(), base), why = r.failure()?.errorText ?? "failed";
      if (path) keep(requests, { method: r.method(), path, ...(why === "net::ERR_ABORTED" ? { aborted: true } : { failed: why }), type: r.resourceType() });
    });
    tab.on("framenavigated", (frame) => {
      if (frame !== tab.mainFrame() || ending) return;
      let url;
      try { url = new URL(frame.url()); } catch { return; }
      if (url.protocol === "chrome-error:") {
        tab.goBack().catch(() => tab.goto(`${base}/${START_ROUTE}`)).catch((e) => log(`coming back from a blocked address: ${firstLine(e)}`));
      } else if (url.protocol.startsWith("http") && !sameServer(url, base)) {
        offsite.push(url.origin);
        tab.goto(`${base}/${START_ROUTE}`).catch((e) => log(`coming back from ${url.origin}: ${firstLine(e)}`));
      }
    });
    fresh.on("page", (p) => { if (p !== tab) p.close().catch(() => null); });
    ctx = fresh;
    page = tab;
    save({ viewport });
    if (previous) await previous.close().catch(() => null);
  }

  try {
    mkdirSync(sessionDir, { recursive: true });
    log("seeding the demo data under the frozen clock");
    await runToEnd(opt.python, ["-m", "waypoint.verify", "seed", "--data", seedDir], process.env);
    await newServer();
    log(`demo server at ${base}`);
    const launch = launchOptions();
    browser = await chromium.launch({ ...launch, args: [...launch.args, ...UNREACHABLE_ARGS] });
    browser.on("disconnected", () => shutdown("the browser closed", 1));
    await openPage(opt.viewport);
    await page.goto(`${base}/${START_ROUTE}`, { waitUntil: "networkidle" });
    await settlePage(page, "start", "start", []);
  } catch (e) {
    log(`start failed: ${e.stack ?? e}`);
    save({ status: "failed", error: firstLine(e) });
    await shutdown("it failed to start", 1, { keepState: true });
    return;
  }

  async function pick(words, { nth, exact = false, timeout = 10000 } = {}) {
    const target = parseTarget(words);
    const found = (target.kind === "role" ? page.getByRole(target.role, target.name ? { name: target.name, exact } : {})
      : target.kind === "text" ? page.getByText(target.text, { exact }) : page.locator(target.selector)).filter({ visible: true });
    const label = target.kind === "role" ? `${target.role}${target.name ? ` "${target.name}"` : ""}` : target.kind === "text" ? `text "${target.text}"` : target.selector;
    try {
      await found.first().waitFor({ state: "visible", timeout });
    } catch (e) {
      if (/Timeout/.test(e.message)) throw new ControlError("no_match", `nothing visible matches ${label} on ${route()}`, `run \`${PROG} snapshot --text\` for the roles and names on the page`);
      throw bad(e);
    }
    const count = await found.count();
    if (nth !== undefined) {
      if (nth >= count) throw new ControlError("no_match", `--nth ${nth}, but only ${count} visible element${count === 1 ? " matches" : "s match"} ${label}`, `use --nth 0 to ${count - 1}`);
      return { loc: found.nth(nth), label: `${label} (match ${nth} of ${count})` };
    }
    if (count > 1) {
      const seen = [];
      for (let i = 0; i < Math.min(count, 6); i++) seen.push(`${i}: ${await describe(found.nth(i))}`);
      throw new ControlError("ambiguous", `${count} visible elements match ${label}: ${seen.join("; ")}${count > 6 ? "; …" : ""}`, `pass --nth <0-${count - 1}>, or name it more exactly (a role and its name, --exact)`);
    }
    return { loc: found.first(), label };
  }

  const describe = (loc) => loc.evaluate((el) => {
    const text = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 50);
    return `${el.getAttribute("role") || el.tagName.toLowerCase()}${text ? ` "${text}"` : ""}`;
  }).catch(() => "(gone)");

  function bad(e) {
    if (e instanceof ControlError) return e;
    const m = firstLine(e);
    if (/ERR_CONNECTION_REFUSED|ECONNREFUSED/.test(m)) return new ControlError("server_gone", "the demo server isn't answering", `run \`${PROG} reset\` (fresh data on a new server), or \`${PROG} stop\` and \`${PROG} start\``);
    if (/Timeout \d+ms exceeded/.test(m)) return new ControlError("timeout", m.replace(/^\w+\.\w+: /, ""), `the page may still be loading (\`${PROG} wait-settle\`), or the target is covered or disabled (\`${PROG} screenshot\` to look)`);
    if (/Unknown key/.test(m)) return new ControlError("bad_key", m, "keys are Playwright's names: Enter, Escape, Tab, Shift+Tab, ArrowDown, Control+a");
    return new ControlError("failed", m, `\`${PROG} screenshot\` and \`${PROG} console\` show what the page did`);
  }

  async function capture(path, { top = false, name = "the page" } = {}) {
    mkdirSync(dirname(path), { recursive: true });
    const notes = [];
    await settlePage(page, name, `${route()} @ ${state.viewport}`, notes);
    await page.screenshot({ path, fullPage: !top, animations: "disabled" });
    return { path: rel(path), fullPage: !top, ...(notes.length ? { notes } : {}) };
  }

  async function info() {
    const size = page.viewportSize();
    return { route: route(), title: await page.title(), viewport: { name: state.viewport, ...size },
      clock: { frozenNow: opt.now, browser: await page.evaluate(() => new Date().toString()), server: `${opt.now.replace("T", " ").replace("Z", "")} UTC, stopped (libfaketime)` },
      session: { pid: process.pid, server: base, idleMinutes: opt.idleMinutes } };
  }

  async function settledNow() {
    const notes = [];
    await settlePage(page, "the page", `${route()} @ ${state.viewport}`, notes, false);
    await page.getByRole("progressbar", { name: "Loading" }).first().waitFor({ state: "hidden", timeout: 5000 }).catch(() => notes.push(`${route()} @ ${state.viewport}: a Loading indicator was still showing after 5 s`));
    return notes.length ? { settled: false, stillLoading: notes } : { settled: true };
  }

  const notReadOnly = (blocked) => new ControlError("not_read_only", `it tried to change the app's data (${blocked.join(", ")}), which was blocked`,
    "pass --write if that's what you meant (demo data only), or use click and type");

  const handlers = {
    async goto({ args, options: o }) {
      await page.goto(routeUrl(base, args[0], host()), { waitUntil: "networkidle" });
      if (o.reload) await page.reload({ waitUntil: "networkidle" });
      await page.waitForTimeout(150);
      return { route: route(), title: await page.title(), ...(await settledNow()) };
    },
    async viewport({ args }) {
      await page.setViewportSize(VIEWPORTS[args[0]]);
      save({ viewport: args[0] });
      return { viewport: { name: args[0], ...VIEWPORTS[args[0]] }, route: route(), ...(await settledNow()) };
    },
    async offline() {
      await setUpOffline(page, base);
      return { offline: "set up", server: `http://localhost:${server.port}`, route: route(), ...(await settledNow()) };
    },
    info,
    async snapshot({ options: o }) {
      const root = o.root ? page.locator(o.root).first() : page.locator("body");
      if (o.root && !(await root.count())) throw new ControlError("no_match", `nothing matches ${o.root}`, `try \`${PROG} snapshot\` without --root`);
      const lines = (await root.ariaSnapshot()).split("\n");
      const max = o["max-lines"];
      return { route: route(), tree: lines.slice(0, max).join("\n"), lines: lines.length, ...(lines.length > max ? { truncated: `${lines.length - max} more lines: narrow it with --root, or raise --max-lines` } : {}) };
    },
    async screenshot({ options: o, path }) {
      const target = path ?? join(dir, "shots", `${String(++shots).padStart(3, "0")}-${shotName(route())}-${state.viewport}.png`);
      const shot = await capture(target, { top: !!o.viewport });
      return { ...shot, route: route(), viewport: state.viewport, next: "look at the image: it is the evidence" };
    },
    async "wait-settle"() { return { route: route(), ...(await settledNow()) }; },
    async click({ args, options: o }) {
      const { loc, label } = await pick(args, o);
      await loc.click({ timeout: o.timeout });
      return { clicked: label, route: route(), ...(await settledNow()) };
    },
    async type({ args, options: o }) {
      const text = args[args.length - 1];
      const { loc, label } = await pick(args.slice(0, -1), o);
      if (await loc.evaluate((el) => el.tagName === "SELECT")) {
        const choices = await loc.evaluate((el) => [...el.options].map((x) => x.label));
        const choice = choices.find((x) => x === text) ?? choices.find((x) => x.toLowerCase().includes(text.toLowerCase()));
        if (choice === undefined) throw new ControlError("no_option", `${label} has no option "${text}"`, `its options: ${choices.join(", ")}`);
        await loc.selectOption({ label: choice }, { timeout: o.timeout });
        return { selected: choice, in: label, route: route(), ...(await settledNow()) };
      }
      await loc.fill(text, { timeout: o.timeout });
      return { typed: text.length, into: label, route: route(), ...(await settledNow()) };
    },
    async press({ args }) {
      await page.keyboard.press(args[0]);
      return { pressed: args[0], route: route(), ...(await settledNow()) };
    },
    async scroll({ args, options: o }) {
      const where = args.join(" ") || "down";
      const size = page.viewportSize();
      if (["up", "down", "top", "bottom"].includes(where)) {
        await page.mouse.move(size.width / 2, size.height / 2);
        await page.mouse.wheel(0, { up: -0.8, down: 0.8, top: -1000, bottom: 1000 }[where] * size.height);
      } else {
        const { loc } = await pick(args, o);
        await loc.scrollIntoViewIfNeeded();
      }
      await page.waitForTimeout(300);
      return { scrolled: where, scrollY: await page.evaluate(() => globalThis.scrollY), route: route() };
    },
    async eval({ args, options: o }) {
      const code = args.join(" ");
      const before = refused.length;
      await page.evaluate(() => {
        globalThis.__controlChanges = 0;
        globalThis.__controlObserver?.disconnect();
        globalThis.__controlObserver = new globalThis.MutationObserver((list) => { globalThis.__controlChanges += list.length; });
        globalThis.__controlObserver.observe(globalThis.document, { subtree: true, childList: true, attributes: true, characterData: true });
      });
      let value;
      try {
        value = await page.evaluate(jsExpression(code));
      } catch (e) {
        if (refused.length > before) throw notReadOnly(refused.splice(before));
        throw new ControlError("eval_error", scrubText(firstLine(e)).replace(/^page\.evaluate: /, ""), "check the expression: it runs in the page (document, window), as an expression or a () => function");
      }
      await page.waitForTimeout(EVAL_SETTLE_MS);
      await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => null);
      const blocked = refused.splice(before);
      const domChanges = await page.evaluate(() => { globalThis.__controlObserver?.disconnect(); return globalThis.__controlChanges ?? 0; }).catch(() => 0);
      if (blocked.length) throw notReadOnly(blocked);
      const json = JSON.stringify(value);
      return { value: json === undefined ? null : json.length > 20000 ? `${json.slice(0, 20000)}… (cut)` : value, type: value === null ? "null" : Array.isArray(value) ? "array" : typeof value, domChanges, ...(domChanges && !o.write ? { warning: "the page changed while it ran (the app re-rendering, or the expression): prefer click and type to change it" } : {}) };
    },
    async console() {
      const messages = consoleBuffer.splice(0);
      return { messages, errors: messages.filter((m) => m.type === "error" || m.type === "pageerror").length };
    },
    async network() {
      const list = requests.splice(0);
      const failed = list.filter((r) => r.failed || r.status >= 400);
      return { requests: list.slice(-200), summary: { total: list.length, failed: failed.length, serverErrors: list.filter((r) => r.status >= 500).length }, ...(list.length > 200 ? { dropped: list.length - 200 } : {}) };
    },
    async flow({ args, options: o }) { return runFlow(args[0], o); },
    async reset() {
      const at = route();
      const here = host();
      const old = server, oldBase = base;
      try { await newServer(); } catch (e) {
        if (server && server !== old) await server.stop().catch(() => null);
        server = old;
        base = oldBase;
        throw new ControlError("reset_failed", `couldn't start a demo server on fresh data: ${firstLine(e)}`, `the session still has its old server and data; try again, or \`${PROG} stop\` and \`${PROG} start\``);
      }
      await old.stop().catch((e) => log(`stopping the old demo server: ${firstLine(e)}`));
      save({ base, port: server.port });
      await openPage(state.viewport);
      await page.goto(`${onHost(base, here)}${at}`, { waitUntil: "networkidle" });
      return { reset: true, server: base, route: route(), ...(await settledNow()) };
    },
  };

  async function usesOfflineSwitch(request) {
    if (request.command !== "flow") return false;
    const { flows } = readFlows(join(HERE, "flows"));
    return !!flows?.find((f) => f.name === request.args?.[0])?.steps.some((step) => "offline" in step);
  }

  async function runFlow(name, o) {
    const { flows, error } = readFlows(join(HERE, "flows"));
    if (error) throw new ControlError("bad_flow", error, "fix the flow file (frontend/verify/flows/README.md has the format)");
    const flow = flows.find((f) => f.name === name);
    if (!flow) {
      const near = closest(name, flows.map((f) => f.name));
      throw new ControlError("no_such_flow", `no flow named ${name}`, near ? `did you mean ${near}? (\`${PROG} flows\` lists them)` : `\`${PROG} flows\` lists them`);
    }
    if (o.viewport && o.viewport !== state.viewport) await handlers.viewport({ args: [o.viewport] });
    const vp = state.viewport;
    const notes = [];
    const wanted = flow.viewports ?? ["phone", "desktop"];
    if (!wanted.includes(vp)) notes.push(`make verify runs ${name} at ${wanted.join(", ")} only; this is ${vp}`);
    notes.push("it ran on this session's data: `reset` first for the data make verify starts it from");
    notes.push("it ran in a new browser, as make verify's flows do; the session is now that browser as the flow left it (`reset` for a fresh one)");
    consoleBuffer.length = 0;
    requests.length = 0;
    const files = [], steps = [], problems = [];
    const out = join(dir, "flows");
    let checks = [];
    const shotAs = async (file) => {
      files.push((await capture(join(out, screenshotFile(file, vp)), { name: file })).path);
      const lost = await recheck(page, checks);
      if (lost) throw new ControlError("check_lost", lost, "taking the screenshot changed the page (a panel closed, focus moved): make verify fails the flow the same way");
    };
    const saveDownload = async (file, download) => {
      const target = join(out, screenshotFile(`flow-${flow.name}-${file}`, vp));
      mkdirSync(out, { recursive: true });
      await download.saveAs(target);
      files.push(rel(target));
    };
    await openPage(vp, flow.phone_agent === true);
    await page.goto(`${onHost(base, flow.host ?? "127.0.0.1")}/#${flow.page ?? "upcoming"}`, { waitUntil: "networkidle" });
    for (const [i, step] of flow.steps.entries()) {
      const started = Date.now();
      try {
        await runStep(page, step, (n) => shotAs(`flow-${flow.name}-${n}`), saveDownload);
        checks = checksAfter(checks, step);
        steps.push({ n: i + 1, step: JSON.stringify(step), ok: true, ms: Date.now() - started });
      } catch (e) {
        steps.push({ n: i + 1, step: JSON.stringify(step), ok: false, ms: Date.now() - started, error: scrubText(firstLine(bad(e).message)) });
        const failedShot = join(out, screenshotFile(`flow-${flow.name}-FAILED`, vp));
        await page.screenshot({ path: failedShot, fullPage: true }).then(() => files.push(rel(failedShot))).catch(() => null);
        problems.push(`step ${i + 1} failed`);
        break;
      }
    }
    if (!problems.length) {
      try { await shotAs(`flow-${flow.name}`); } catch (e) { problems.push(`the last screenshot: ${firstLine(e)}`); }
    }
    const allowed = flow.allow_console ?? [];
    for (const m of consoleBuffer) if ((m.type === "error" || m.type === "pageerror") && !allowed.some((t) => m.text.includes(t))) problems.push(`console ${m.type}: ${m.text}`);
    for (const r of requests) if (r.status >= 500) problems.push(`${r.status} from ${r.method} ${r.path}`);
    const result = { flow: name, viewport: vp, steps, files, notes };
    if (problems.length) throw Object.assign(new ControlError("flow_failed", `${name} failed: ${problems.join("; ")}`, "the -FAILED- image and `console` show what the page did; make verify would fail the same way"), { data: result });
    return result;
  }

  let queue = Promise.resolve();
  const sameToken = (t) => typeof t === "string" && t.length === token.length && timingSafeEqual(Buffer.from(t), Buffer.from(token));

  async function handle(request) {
    if (!sameToken(request.token)) return errorResult(request.command, new ControlError("forbidden", "wrong token: this isn't the session's caller", `use ${PROG}, which reads the token from the state file`));
    if (request.command === "stop") { setTimeout(() => shutdown("stop"), 50); return { ok: true, stopping: true }; }
    const handler = handlers[request.command];
    if (!handler) { touch(); return errorResult(request.command, new ControlError("usage", `the session has no command ${request.command}`, `\`${PROG} --help\``, 2)); }
    log(`${request.command}`);
    clearTimeout(idle);
    acting = ACTING_COMMANDS.includes(request.command) || (request.command === "eval" && !!request.options?.write);
    await guardWrites(!acting);
    await blockOffServer(!(await usesOfflineSwitch(request)));
    try {
      const reply = await handler({ args: request.args ?? [], options: request.options ?? {}, path: request.path });
      const away = offsite.splice(0);
      const stopped = blockedHosts.splice(0);
      const idleWrites = refused.splice(0);
      const warnings = [
        ...(away.length ? [`the page went to ${away.join(", ")}, which isn't the session's server: it was brought back`] : []),
        ...(stopped.length ? [`requests to ${uniqueList(stopped).join(", ")}, which isn't the session's server, were blocked before they were sent`] : []),
        ...(idleWrites.length && request.command !== "eval" ? [`${idleWrites.length} change(s) the page tried to make while no command was acting were blocked (${uniqueList(idleWrites).slice(0, 3).join(", ")})`] : []),
      ];
      return { ok: true, ...reply, ...(warnings.length ? { warning: warnings.join("; ") } : {}) };
    } catch (e) {
      const err = bad(e);
      return { ...errorResult(request.command, err), ...(e.data ?? {}) };
    } finally {
      acting = false;
      await guardWrites(true).catch((e) => log(`guarding writes: ${firstLine(e)}`));
      await blockOffServer(true).catch((e) => log(`blocking other addresses: ${firstLine(e)}`));
      touch();
    }
  }

  if (existsSync(socket)) rmSync(socket, { force: true });
  listener = createServer((conn) => {
    let data = "";
    conn.on("data", (d) => {
      data += d;
      if (data.length > 1e6) { conn.destroy(); return; }
      const end = data.indexOf("\n");
      if (end < 0) return;
      let request;
      try { request = JSON.parse(data.slice(0, end)); } catch { conn.end(JSON.stringify(errorResult(null, new ControlError("usage", "not a request", `use ${PROG}`)))); return; }
      queue = queue.then(() => handle(request)).then((reply) => { conn.end(JSON.stringify(reply)); });
    });
    conn.on("error", () => null);
  });
  await new Promise((resolve, reject) => { listener.once("error", reject); listener.listen(socket, resolve); });
  chmodSync(socket, 0o600);
  try { shots = lastShotNumber(readdirSync(join(dir, "shots"))); } catch { shots = 0; }
  await guardWrites(true);
  await blockOffServer(true);
  touch();
  save({ status: "ready", base, port: server.port, route: route(), clock: { frozenNow: opt.now, browser: await page.evaluate(() => new Date().toString()) } });
  log(`ready at ${base}`);
}

main().catch((e) => { log(`fatal: ${e.stack ?? e}`); process.exit(1); });
