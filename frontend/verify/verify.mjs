import { chromium } from "@playwright/test";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { animationsRunning, auditPage } from "./a11y.mjs";
import { planVisits, runPool, summarize, urlsOf } from "./jobs.mjs";

export const PHONE_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
export const VIEWPORTS = { phone: { width: 440, height: 956 }, desktop: { width: 1280, height: 800 }, laptop: { width: 1024, height: 768 }, wide: { width: 1440, height: 900 }, zoomed: { width: 853, height: 533 } };
export const DEFAULT_VIEWPORTS = ["phone", "desktop"];
export const IMAGE_VIEWPORTS = ["phone", "desktop"];
export const CHROMIUM_ARGS = ["--force-color-profile=srgb", "--disable-lcd-text", "--num-raster-threads=1"];
export const launchOptions = () => ({ executablePath: findChromium(), args: CHROMIUM_ARGS });
export const contextOptions = (viewport, { reducedMotion = "no-preference", phoneAgent = false } = {}) => ({ viewport: VIEWPORTS[viewport], colorScheme: "dark", timezoneId: "UTC", reducedMotion, ...(phoneAgent && viewport === "phone" ? { userAgent: PHONE_AGENT } : {}) });
export const prepareContext = (ctx, now) => ctx.clock.setFixedTime(now);
export const SETTLE_MS = 300;
export const FROZEN_NOW = "2026-06-15T12:00:00Z";
export const PAGES = ["upcoming", "trips", "stats", "people", "review", "settings", "design", "oauth-approve"];
export const OWN_PAGES = ["oauth-approve"];

export function findChromium(env = process.env, exists = existsSync, list = readdirSync) {
  const root = env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!exists(root)) return undefined;
  for (const dir of list(root).filter((d) => d.startsWith("chromium-")).sort().reverse()) {
    for (const sub of ["chrome-linux64/chrome", "chrome-linux/chrome"]) {
      const p = join(root, dir, sub);
      if (exists(p)) return p;
    }
  }
  return undefined;
}

export const screenshotFile = (name, viewport) => `${name}-${viewport}.png`;
export const heroFile = (name, viewport) => `${name}-${viewport}-hero.png`;
export const writesImage = (viewport) => IMAGE_VIEWPORTS.includes(viewport);
export const localBase = (base) => base.replace("127.0.0.1", "localhost");
export const VIRTUAL_AUTHENTICATOR = { protocol: "ctap2", ctap2Version: "ctap2_1", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true, hasPrf: true };
export const OFFLINE_SAVED = "[data-testid='offline-saved']:text-matches('^\\s*Saved [0-9]|^\\s*Saved just now')";

const ACTIONS = { goto: "string", click: "string", click_if_present: "string", hover: "string", select: "object", fill: "object", press: "object", upload: "object", download: "object", scroll_to: "string", authenticator: "string", offline: "boolean", reload: "boolean", long_names: "string", fake_labels: "string", fake_ignored: "string", fake_ignore: "string", fake_destination: "string", fake_first_run: "string", fake_merge_warning: "string", fake_archive: "number", wait_for: "string", expect_text: "object", screenshot: "string" };
const LONG_NAME_KEYS = new Set(["name", "city", "hotel"]);

export function lengthenNames(value, suffix) {
  if (Array.isArray(value)) return value.map((v) => lengthenNames(v, suffix));
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, LONG_NAME_KEYS.has(k) && typeof v === "string" ? v + suffix : lengthenNames(v, suffix)]));
}
const ARCHIVE_PLACES = [["Lisbon", "TAP Air Portugal"], ["Denver", "United Airlines"], ["Tokyo", "All Nippon Airways"], ["Chicago", "American Airlines"], ["Reykjavik", "Icelandair"], ["Mexico City", "Delta Air Lines"], ["Sydney", "Qantas"], ["Seattle", "Alaska Airlines"], ["Rome", "ITA Airways"], ["Vancouver", "Air Canada"]];

export function fakeArchive(trips, count) {
  const model = trips.find((t) => t.segments.length) ?? trips[0];
  if (!model) return [];
  const first = Math.max(0, ...trips.map((t) => t.id)) + 1;
  return Array.from({ length: count }, (_, i) => {
    const [city, airline] = ARCHIVE_PLACES[i % ARCHIVE_PLACES.length];
    const year = 2025 - Math.floor(i / 60);
    const month = String(1 + (i % 12)).padStart(2, "0");
    const day = String(1 + (i % 27)).padStart(2, "0");
    const start = `${year}-${month}-${day}`;
    const end = `${year}-${month}-${String(Number(day) + 1).padStart(2, "0")}`;
    const id = first + i;
    const segments = model.segments.slice(0, 1).map((s) => ({ ...s, id: id * 10, trip_id: id, provider: airline, destination: city, start_local: `${start}T09:00`, end_local: `${end}T12:00` }));
    return { ...model, id, name: `Trip to ${city} ${i + 1}`, destination: city, start_date: start, end_date: end, segments, emails: 0, can_clear_emails: false };
  });
}

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const unknownPages = (names) => names.filter((n) => !PAGES.includes(n));

export function flowProblems(flow) {
  const out = [];
  if (!flow || typeof flow.name !== "string" || !/^[\w-]+$/.test(flow.name)) out.push("needs a name of letters, digits, - or _");
  if (!Array.isArray(flow?.steps) || !flow.steps.length) out.push("needs a list of steps");
  for (const [i, s] of (flow?.steps ?? []).entries()) {
    const keys = Object.keys(s).filter((k) => k !== "timeout");
    if (keys.length !== 1 || !(keys[0] in ACTIONS)) out.push(`step ${i + 1} must have exactly one of ${Object.keys(ACTIONS).join(", ")}`);
    else if (typeof s[keys[0]] !== ACTIONS[keys[0]]) out.push(`step ${i + 1}: ${keys[0]} takes a ${ACTIONS[keys[0]]}`);
    else if (keys[0] === "download" && (typeof s.download?.selector !== "string" || !/^[\w-]+$/.test(s.download?.name ?? ""))) out.push(`step ${i + 1}: download needs a selector and a name of letters, digits, - or _`);
  }
  if (flow?.page !== undefined && !PAGES.includes(flow.page)) out.push(`unknown page ${flow.page}`);
  for (const v of flow?.viewports ?? []) if (!(v in VIEWPORTS)) out.push(`unknown viewport ${v}`);
  if (flow?.host !== undefined && !/^[\w.-]+$/.test(flow.host)) out.push("host is a host name such as localhost");
  if (flow?.allow_console !== undefined && !(Array.isArray(flow.allow_console) && flow.allow_console.every((t) => typeof t === "string"))) out.push("allow_console is a list of texts");
  if (flow?.phone_agent !== undefined && typeof flow.phone_agent !== "boolean") out.push("phone_agent is true or false");
  if (flow?.scheme !== undefined) out.push("scheme is not an option: the app is dark only");
  return out;
}

const REDIRECT = "http://127.0.0.1:33418/callback";
const pkce = () => { const verifier = randomBytes(32).toString("base64url"); return { verifier, challenge: createHash("sha256").update(verifier).digest("base64url") }; };

export async function seedAssistants(browser, base) {
  const ctx = await browser.newContext();
  try {
    const post = (path, options) => ctx.request.post(`${base}${path}`, { headers: { "X-Waypoint": "1", Origin: base }, ...options });
    const register = async (name) => (await (await post("/oauth/register", { data: { client_name: name, redirect_uris: [REDIRECT] } })).json()).client_id;
    const askUrl = (clientId, challenge) => `${base}/oauth/authorize?` + new URLSearchParams({ response_type: "code", client_id: clientId,
      redirect_uri: REDIRECT, scope: "read write", state: "demo", code_challenge: challenge, code_challenge_method: "S256", resource: `${base}/mcp` });
    await post("/api/mcp-settings/writes", { data: { allow: true } });
    for (const [name, change] of [["Claude", true], ["Claude Code", false]]) {
      const { verifier, challenge } = pkce();
      const clientId = await register(name);
      const page = await ctx.newPage();
      const answered = new Promise((resolve) => page.on("requestfailed", (r) => { if (r.url().startsWith(REDIRECT)) resolve(r.url()); }));
      await page.goto(askUrl(clientId, challenge));
      if (change) await page.locator("input[name=write]").check();
      await page.locator("button[value=allow]").click();
      await answered;
      const code = new URL(await answered).searchParams.get("code");
      if (!code) throw new Error(`seeding ${name}: the approval page gave no code`);
      const token = await (await post("/oauth/token", { form: { grant_type: "authorization_code", code, redirect_uri: REDIRECT, client_id: clientId,
        code_verifier: verifier, resource: `${base}/mcp` } })).json();
      if (!token.access_token) throw new Error(`seeding ${name}: no token (${JSON.stringify(token).slice(0, 80)})`);
      if (change) await post("/mcp", { headers: { Authorization: `Bearer ${token.access_token}`, "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
        data: { jsonrpc: "2.0", id: 1, method: "tools/list" } });
      await page.close();
    }
    return askUrl(await register("Claude Desktop"), pkce().challenge);
  } finally { await ctx.close(); }
}

async function addAuthenticator(page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", { options: VIRTUAL_AUTHENTICATOR });
}

export async function setUpOffline(page, base, timeout = 10000) {
  await addAuthenticator(page);
  await page.goto(`${localBase(base)}/#settings/offline`, { waitUntil: "networkidle" });
  await page.locator("button:has-text('Set up offline access')").first().click({ timeout });
  await page.locator("button:has-text('Turn on with')").first().click({ timeout });
  await page.locator(OFFLINE_SAVED).first().waitFor({ timeout });
  await page.mouse.move(0, 0);
}

export async function runStep(page, step, shot, saveDownload) {
  const timeout = step.timeout ?? 10000;
  if ("authenticator" in step) {
    await addAuthenticator(page);
  } else if ("offline" in step) {
    await page.context().setOffline(step.offline);
  } else if ("reload" in step) {
    await page.reload({ waitUntil: "domcontentloaded", timeout });
  } else if ("fake_labels" in step) {
    const names = step.fake_labels.split(",").map((n) => n.trim()).filter(Boolean);
    await page.route("**/api/mailboxes/*/labels", async (route) => {
      if (route.request().method() === "POST") return route.fulfill({ json: { ok: true } });
      return route.fulfill({ json: { labels: names.map((name, i) => ({ id: `Label_${i + 1}`, name, count: (i + 1) * 4, picked: false })) } });
    });
  } else if ("fake_ignored" in step) {
    let domains = step.fake_ignored.split(",").map((n) => n.trim()).filter(Boolean);
    await page.route("**/api/mailboxes/*/ignored", (route) => route.fulfill({ json: { domains } }));
    await page.route("**/api/mailboxes/*/unignore", async (route) => {
      domains = domains.filter((d) => d !== route.request().postDataJSON()?.domain);
      await route.fulfill({ json: { started: true } });
    });
  } else if ("fake_ignore" in step) {
    await page.route("**/api/review/*/ignore", (route) => route.fulfill({ json: { ok: true, mailbox_id: 1, domain: step.fake_ignore } }));
  } else if ("fake_destination" in step) {
    await page.route("**/api/state", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), ai: true } });
    });
    await page.route("**/api/trips/*/destination/suggest", (route) => route.fulfill({ json: { suggestion: step.fake_destination } }));
  } else if ("fake_first_run" in step) {
    const mailbox = { id: 1, address: "jane@example.test", status: "connected", last_error: null, last_scan: null, scan_error: null, scanning: step.fake_first_run === "scanning", scan_notice: null,
      scan_summary: null, reading_again: null, labels_picked: 0, share_review: false };
    const mailboxes = step.fake_first_run === "connect" ? [] : [mailbox];
    await page.route("**/api/trips", (route) => route.fulfill({ json: { trips: [] } }));
    await page.route("**/api/people/claim-suggestions", (route) => route.fulfill({ json: { guests: [] } }));
    await page.route("**/api/mailboxes", (route) => route.fulfill({ json: { configured: true, mailboxes } }));
    await page.route("**/api/state", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), review_count: step.fake_first_run === "review" ? 3 : 0 } });
    });
  } else if ("fake_archive" in step) {
    const made = new Map();
    await page.route("**/api/trips", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const added = fakeArchive(body.trips, step.fake_archive);
      for (const t of added) made.set(String(t.id), t);
      await route.fulfill({ response, json: { ...body, trips: [...body.trips, ...added] } });
    });
    await page.route(/\/api\/trips\/\d+(\/places)?$/, (route) => {
      const [, id, places] = /\/api\/trips\/(\d+)(\/places)?$/.exec(new URL(route.request().url()).pathname) ?? [];
      const t = made.get(id);
      if (!t || route.request().method() !== "GET") return route.fallback();
      return route.fulfill({ json: places ? { home: null, airports: [], cities: [], stays: [], roads: { legs: [], interstates: [] }, boundaries: [] } : t });
    });
  } else if ("fake_merge_warning" in step) {
    const [first, second] = step.fake_merge_warning.split("|").map((part) => part.split(",").map((n) => n.trim()).filter(Boolean));
    const named = (names = []) => names.map((name, i) => ({ id: i + 1, name }));
    await page.route("**/api/trips/*/merge", async (route) => {
      if (route.request().postDataJSON()?.confirm) return route.continue();
      return route.fulfill({ status: 409, json: { error: "Merging these trips changes who sees what.", see_booking: named(first), see_trip: named(second) } });
    });
  } else if ("long_names" in step) {
    await page.route("**/api/stats**", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: lengthenNames(await response.json(), step.long_names) });
    });
  } else if ("goto" in step) {
    await page.goto(step.goto.startsWith("#") ? `${page.url().split("#")[0]}${step.goto}` : step.goto);
  } else if ("click" in step) {
    await page.locator(step.click).first().click({ timeout });
  } else if ("click_if_present" in step) {
    const target = page.locator(step.click_if_present).first();
    const present = await target.waitFor({ state: "visible", timeout: step.timeout ?? 1000 }).then(() => true, () => false);
    if (present) await target.click({ timeout });
  } else if ("hover" in step) {
    await page.locator(step.hover).first().hover({ timeout });
  } else if ("select" in step) {
    await page.locator(step.select.selector).first().selectOption({ index: step.select.index }, { timeout });
  } else if ("fill" in step) {
    await page.locator(step.fill.selector).first().fill(step.fill.text, { timeout });
  } else if ("press" in step) {
    await page.locator(step.press.selector).first().press(step.press.key, { timeout });
  } else if ("upload" in step) {
    await page.locator(step.upload.selector).first().setInputFiles(join(REPO, step.upload.file), { timeout });
  } else if ("download" in step) {
    const pending = page.waitForEvent("download", { timeout });
    await page.locator(step.download.selector).first().click({ timeout });
    await saveDownload(step.download.name, await pending);
  } else if ("scroll_to" in step) {
    await page.locator(step.scroll_to).first().evaluate((el) => el.scrollIntoView({ block: "start" }), undefined, { timeout });
  } else if ("wait_for" in step) {
    await page.locator(step.wait_for).first().waitFor({ timeout });
  } else if ("expect_text" in step) {
    const el = page.locator(step.expect_text.selector).first();
    await el.waitFor({ timeout });
    const until = Date.now() + timeout;
    let got = await el.innerText();
    while (!got.includes(step.expect_text.text) && Date.now() < until) {
      await page.waitForTimeout(100);
      got = await el.innerText();
    }
    if (!got.includes(step.expect_text.text)) throw new Error(`expected "${step.expect_text.text}" in ${step.expect_text.selector}, found "${got.slice(0, 80)}"`);
  } else if ("screenshot" in step) {
    await shot(step.screenshot);
  }
}

const NEUTRAL_STEPS = ["wait_for", "screenshot", "scroll_to"];

export function checksAfter(checks, step) {
  const action = Object.keys(step).find((k) => k !== "timeout");
  if (action === "expect_text") return [...checks, step];
  return NEUTRAL_STEPS.includes(action) ? checks : [];
}

export async function recheck(page, checks, timeout = 2000) {
  for (const step of checks) {
    try { await runStep(page, { ...step, timeout }, null, null); }
    catch (e) { return `${JSON.stringify(step).slice(0, 80)} no longer holds after the screenshot: ${String(e.message).split("\n")[0]}`; }
  }
  return null;
}

export async function warmMaps(browser, base) {
  const ctx = await browser.newContext();
  try {
    const get = (path) => ctx.request.get(`${base}${path}`, { timeout: 180000 });
    const { trips } = await (await get("/api/trips")).json();
    for (const t of trips) await get(`/api/trips/${t.id}/places`);
  } finally { await ctx.close(); }
}

export async function settlePage(page, name, where, notes, scrollToTop = true) {
  if (scrollToTop) await page.evaluate(`window.scrollTo({ top: 0, left: 0, behavior: "instant" })`);
  try { await page.waitForLoadState("networkidle", { timeout: 3000 }); } catch { notes.push(`${where}: still loading after 3 s when ${name} was captured`); }
  await page.evaluate("document.fonts.ready");
  try { await page.waitForFunction(() => globalThis.document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity), undefined, { timeout: 3000 }); }
  catch { notes.push(`${where}: an animation was still running after 3 s when ${name} was captured`); }
  await page.waitForTimeout(SETTLE_MS);
}

async function visit(env, label, viewport, work, { audit = true, reducedMotion = "no-preference", allowConsole = [], phoneAgent = false } = {}) {
  const { browser, now, images, out } = env;
  const ctx = await browser.newContext(contextOptions(viewport, { reducedMotion, phoneAgent }));
  try {
    await prepareContext(ctx, now);
    const page = await ctx.newPage();
    const where = `${label} @ ${viewport}`;
    const problems = [];
    const notes = [];
    const consoleErrors = [];
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => consoleErrors.push(`uncaught: ${e.message}`));
    page.on("response", (r) => { if (r.status() >= 500) problems.push(`${where}: ${r.status()} from ${r.request().method()} ${new URL(r.url()).pathname}`); });
    page.on("requestfailed", (r) => { if (r.failure()?.errorText !== "net::ERR_ABORTED") notes.push(`${where}: request failed (${r.failure()?.errorText}) ${new URL(r.url()).pathname}`); });
    const files = [];
    const shot = async (name, dir = images, hero = false) => {
      if (!writesImage(viewport)) return;
      const file = screenshotFile(name, viewport);
      await settlePage(page, name, where, notes);
      await page.screenshot({ path: join(dir, file), fullPage: true, animations: "disabled" });
      files.push(file);
      if (!hero) return;
      const top = heroFile(name, viewport);
      await page.screenshot({ path: join(dir, top), fullPage: false, animations: "disabled" });
      files.push(top);
    };
    const saveDownload = async (name, download, dir = images) => {
      if (!writesImage(viewport)) return;
      const file = screenshotFile(name, viewport);
      await download.saveAs(join(dir, file));
      files.push(file);
    };
    try {
      await work(page, shot, saveDownload);
      if (audit) for (const p of await auditPage(page, viewport)) problems.push(`${where}: a11y ${p}`);
    } catch (e) {
      problems.push(`${where}: ${String(e.message).split("\n")[0]}`);
      await shot(`${label.replace(/\W+/g, "-")}-FAILED`, out).catch(() => {});
    }
    for (const c of consoleErrors.filter((c) => !allowConsole.some((t) => c.includes(t)))) problems.push(`${where}: console error: ${c.slice(0, 300)}`);
    return { screenshots: files, consoleErrors, problems, notes };
  } finally { await ctx.close(); }
}

export function runVisit(env, v) {
  const { base, approveUrl } = env;
  if (v.kind === "flow") {
    const { flow } = v;
    return visit(env, `flow ${flow.name}`, v.viewport, async (page, shot, saveDownload) => {
      await page.goto(`${flow.host ? base.replace("127.0.0.1", flow.host) : base}/#${flow.page ?? "upcoming"}`, { waitUntil: "networkidle" });
      let checks = [];
      const shotChecked = async (file) => {
        await shot(file, env.out);
        const lost = await recheck(page, checks);
        if (lost) throw new Error(lost);
      };
      for (const [i, step] of flow.steps.entries()) {
        try { await runStep(page, step, (n) => shotChecked(`flow-${flow.name}-${n}`), (n, d) => saveDownload(`flow-${flow.name}-${n}`, d, env.out)); }
        catch (e) { throw new Error(`step ${i + 1} (${JSON.stringify(step).slice(0, 80)}): ${String(e.message).split("\n")[0]}`, { cause: e }); }
        checks = checksAfter(checks, step);
      }
      await shotChecked(`flow-${flow.name}`);
    }, { allowConsole: flow.allow_console, phoneAgent: flow.phone_agent === true });
  }
  if (v.kind === "reduced") {
    return visit(env, `reduced motion ${v.name}`, v.viewport, async (page) => {
      await page.goto(`${base}/#${v.name}`, { waitUntil: "networkidle" });
      const moving = await animationsRunning(page);
      if (moving.length) throw new Error(`animations still run under prefers-reduced-motion: ${moving.slice(0, 5).join(", ")}`);
    }, { audit: false, reducedMotion: "reduce" });
  }
  return visit(env, v.name, v.viewport, async (page, shot) => {
    if (OWN_PAGES.includes(v.name)) {
      if (!approveUrl) throw new Error("no approval page: seeding the demo assistants failed");
      await page.goto(approveUrl, { waitUntil: "networkidle" });
      await page.locator("button[value=allow]").waitFor({ timeout: 10000 });
    } else {
      await setUpOffline(page, base);
      await page.goto("about:blank");
      await page.goto(`${localBase(base)}/#${v.name}`, { waitUntil: "networkidle" });
    }
    await shot(v.name, env.images, true);
  });
}

export function readFlows(flowsDir) {
  if (!existsSync(flowsDir)) return { flows: [] };
  const flows = [];
  for (const f of readdirSync(flowsDir).filter((x) => x.endsWith(".json")).sort()) {
    let flow;
    try { flow = JSON.parse(readFileSync(join(flowsDir, f), "utf8")); } catch (e) { return { error: `flow ${f} isn't valid JSON (${e.message})` }; }
    const bad = flowProblems(flow);
    if (bad.length) return { error: `flow ${f}: ${bad.join("; ")}` };
    flows.push(flow);
  }
  return { flows };
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args.splice(i, 2)[1]; };
  const optAll = (name) => { const found = []; for (let i = args.indexOf(name); i >= 0; i = args.indexOf(name)) found.push(args.splice(i, 2)[1]); return found; };
  const given = optAll("--url").flatMap(urlsOf);
  const urls = [...(given.length ? given : urlsOf(process.env.WAYPOINT_VERIFY_URL))].filter((u, i, all) => all.indexOf(u) === i);
  const here = dirname(fileURLToPath(import.meta.url));
  const out = opt("--out", join(here, "../../artifacts/verify"));
  const images = opt("--images", join(here, "../../docs/src/assets/screenshots"));
  const now = new Date(opt("--now", process.env.WAYPOINT_VERIFY_NOW ?? FROZEN_NOW));
  const flowsDir = opt("--flows", join(here, "flows"));
  const only = optAll("--flow").flatMap(urlsOf);
  if (!urls.length) { console.error("verify: no server address (--url or WAYPOINT_VERIFY_URL)"); process.exit(2); }
  const unknown = unknownPages(args);
  if (unknown.length) { console.error(`verify: no such page: ${unknown.join(", ")} (pages: ${PAGES.join(", ")})`); process.exit(2); }
  const { flows: everyFlow, error: flowError } = readFlows(flowsDir);
  if (flowError) { console.error(`verify: ${flowError}`); process.exit(2); }
  const missing = only.filter((n) => !everyFlow.some((f) => f.name === n));
  if (missing.length) { console.error(`verify: no such flow: ${missing.join(", ")}`); process.exit(2); }
  const pages = args.length ? args : PAGES;
  const flows = only.length ? everyFlow.filter((f) => only.includes(f.name)) : everyFlow;
  const visits = planVisits({ pages, flows, viewports: DEFAULT_VIEWPORTS, ownPages: OWN_PAGES, filtered: args.length > 0 || only.length > 0, flowsOnly: only.length > 0 });

  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  if (!args.length && !only.length) rmSync(images, { recursive: true, force: true });
  mkdirSync(images, { recursive: true });
  const started = Date.now();
  const startup = [];
  const { outcomes, failures } = await runPool({
    visits,
    workers: urls.length,
    prepare: async (worker) => {
      const base = urls[worker];
      const browser = await chromium.launch(launchOptions());
      let approveUrl = "";
      try { approveUrl = await seedAssistants(browser, base); }
      catch (e) { startup.push({ worker, reason: `seeding the demo assistants: ${String(e.message).split("\n")[0]}` }); }
      try { await warmMaps(browser, base); }
      catch (e) { startup.push({ worker, reason: `warming the map data: ${String(e.message).split("\n")[0]}` }); }
      return { browser, base, approveUrl, now, images, out };
    },
    work: (v, env) => runVisit(env, v),
    release: (env) => env.browser.close(),
  });
  const { problems, notes, results } = summarize({ outcomes, failures, startup, urls });
  const seconds = Math.round((Date.now() - started) / 1000);

  writeFileSync(join(out, "report.json"), JSON.stringify({ base: urls[0], instances: urls, seconds, results, problems, notes }, null, 2));
  const shots = results.reduce((n, r) => n + r.screenshots.length, 0);
  console.log(`verify: ${results.length} visits, ${shots} screenshots in ${images}, ${seconds} s on ${urls.length} server${urls.length === 1 ? "" : "s"}`);
  for (const n of notes) console.log(`  note: ${n}`);
  for (const p of problems) console.error(`  FAIL: ${p}`);
  console.log(problems.length ? `verify: FAILED (${problems.length} problem${problems.length === 1 ? "" : "s"})` : "verify: OK, no console errors, 5xx responses or accessibility problems");
  process.exit(problems.length ? 1 : 0);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main().catch((e) => { console.error(e); process.exit(2); });
