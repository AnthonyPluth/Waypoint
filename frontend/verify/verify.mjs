// Drives the running app with Playwright and collects proof: a screenshot of each page (full page, and the top of it) at phone, tablet and desktop
// widths, plus console errors and failed requests. Started by `python run.py verify` (waypoint/verify.py), which owns the
// demo database and the server; run alone it needs a server that already has the demo data.
//
//   node verify/verify.mjs --url http://127.0.0.1:8765 --out ../artifacts/verify [page…]
//
// Exits 1 on a console error, an uncaught page error, a 5xx response or a failed scripted step.
import { chromium } from "@playwright/test";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const VIEWPORTS = { phone: { width: 390, height: 844 }, tablet: { width: 768, height: 1024 }, desktop: { width: 1280, height: 800 } };
export const PAGES = ["upcoming", "trips", "people", "review", "settings"];
export const SCHEMES = ["light", "dark"];   // a flow's colour scheme (the app follows the device's: prefers-color-scheme)

/** The browser to launch: the Chromium preinstalled under PLAYWRIGHT_BROWSERS_PATH (or /opt/pw-browsers) when there is
 *  one, whatever its revision, otherwise undefined (Playwright's own download). */
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

/** The two files one screenshot makes: the full page, and `-top`, just the viewport (the top of the page), which is the one
 *  that fits in a pull request (`make pr-screenshots`). */
export const screenshotFiles = (name, viewport) => ({ full: `${name}-${viewport}.png`, top: `${name}-${viewport}-top.png` });

/** A flow is { name, page?, viewports?, steps: [ { goto | click | fill | press | upload | scroll_to | wait_for | expect_text | screenshot } ] }:
 *  see frontend/verify/flows/README.md. Returns the problems with it, [] when it's well formed. */
const ACTIONS = { goto: "string", click: "string", fill: "object", press: "object", upload: "object", scroll_to: "string", wait_for: "string", expect_text: "object", screenshot: "string" };
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
  }
  if (flow?.page !== undefined && !PAGES.includes(flow.page)) out.push(`unknown page ${flow.page}`);
  for (const v of flow?.viewports ?? []) if (!(v in VIEWPORTS)) out.push(`unknown viewport ${v}`);
  if (flow?.scheme !== undefined && !SCHEMES.includes(flow.scheme)) out.push(`unknown scheme ${flow.scheme}`);
  return out;
}

async function runStep(page, step, shot) {
  const timeout = step.timeout ?? 10000;
  if ("goto" in step) {
    await page.goto(step.goto.startsWith("#") ? `${page.url().split("#")[0]}${step.goto}` : step.goto);
  } else if ("click" in step) {
    await page.locator(step.click).first().click({ timeout });
  } else if ("fill" in step) {
    await page.locator(step.fill.selector).first().fill(step.fill.text, { timeout });
  } else if ("press" in step) {
    await page.locator(step.press.selector).first().press(step.press.key, { timeout });
  } else if ("upload" in step) {
    await page.locator(step.upload.selector).first().setInputFiles(join(REPO, step.upload.file), { timeout });   // a file of the repo (made-up data)
  } else if ("scroll_to" in step) {
    await page.locator(step.scroll_to).first().evaluate((el) => el.scrollIntoView({ block: "start" }), undefined, { timeout });
  } else if ("wait_for" in step) {
    await page.locator(step.wait_for).first().waitFor({ timeout });
  } else if ("expect_text" in step) {
    const el = page.locator(step.expect_text.selector).first();
    await el.waitFor({ timeout });
    const got = await el.innerText();
    if (!got.includes(step.expect_text.text)) throw new Error(`expected "${step.expect_text.text}" in ${step.expect_text.selector}, found "${got.slice(0, 80)}"`);
  } else if ("screenshot" in step) {
    await shot(step.screenshot);
  }
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args.splice(i, 2)[1]; };
  const base = opt("--url", process.env.WAYPOINT_VERIFY_URL);
  const here = dirname(fileURLToPath(import.meta.url));
  const out = opt("--out", join(here, "../../artifacts/verify"));
  const flowsDir = opt("--flows", join(here, "flows"));
  if (!base) { console.error("verify: no server address (--url or WAYPOINT_VERIFY_URL)"); process.exit(2); }
  const unknown = unknownPages(args);
  if (unknown.length) { console.error(`verify: no such page: ${unknown.join(", ")} (pages: ${PAGES.join(", ")})`); process.exit(2); }
  const pages = args.length ? args : PAGES;

  const flows = existsSync(flowsDir) ? readdirSync(flowsDir).filter((f) => f.endsWith(".json")).sort().map((f) => {
    let flow;
    try { flow = JSON.parse(readFileSync(join(flowsDir, f), "utf8")); } catch (e) { console.error(`verify: flow ${f} isn't valid JSON (${e.message})`); process.exit(2); }
    const bad = flowProblems(flow);
    if (bad.length) { console.error(`verify: flow ${f}: ${bad.join("; ")}`); process.exit(2); }
    return flow;
  }) : [];

  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: findChromium() });
  const problems = [];   // what makes the run fail
  const notes = [];      // what's only reported
  const results = [];

  async function visit(label, viewport, work, scheme = "light") {
    const ctx = await browser.newContext({ viewport: VIEWPORTS[viewport], colorScheme: scheme });
    const page = await ctx.newPage();
    const where = `${label} @ ${viewport}`;
    const consoleErrors = [];
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => consoleErrors.push(`uncaught: ${e.message}`));
    page.on("response", (r) => { if (r.status() >= 500) problems.push(`${where}: ${r.status()} from ${r.request().method()} ${new URL(r.url()).pathname}`); });
    page.on("requestfailed", (r) => { if (r.failure()?.errorText !== "net::ERR_ABORTED") notes.push(`${where}: request failed (${r.failure()?.errorText}) ${new URL(r.url()).pathname}`); });
    const files = [];
    const shot = async (name) => {
      const { full, top } = screenshotFiles(name, viewport);
      await page.screenshot({ path: join(out, full), fullPage: true });
      files.push(full);
      await page.screenshot({ path: join(out, top) });
      files.push(top);
    };
    try {
      await work(page, shot);
    } catch (e) {
      problems.push(`${where}: ${String(e.message).split("\n")[0]}`);
      // The failure screenshot is best effort: the step's own error is already recorded above.
      await shot(`${label.replace(/\W+/g, "-")}-FAILED`).catch(() => {});
    }
    for (const c of consoleErrors) problems.push(`${where}: console error: ${c.slice(0, 300)}`);
    results.push({ label, viewport, screenshots: files, consoleErrors });
    await ctx.close();
  }

  for (const name of pages) {
    for (const viewport of Object.keys(VIEWPORTS)) {
      await visit(name, viewport, async (page, shot) => {
        await page.goto(`${base}/#${name}`, { waitUntil: "networkidle" });
        await shot(name);
      });
    }
  }
  for (const flow of flows) {
    if (args.length && !args.includes(flow.page ?? "upcoming")) continue;
    for (const viewport of flow.viewports ?? Object.keys(VIEWPORTS)) {
      await visit(`flow ${flow.name}`, viewport, async (page, shot) => {
        await page.goto(`${base}/#${flow.page ?? "upcoming"}`, { waitUntil: "networkidle" });
        for (const step of flow.steps) await runStep(page, step, (n) => shot(`flow-${flow.name}-${n}`));
        await shot(`flow-${flow.name}`);
      }, flow.scheme);
    }
  }
  await browser.close();

  writeFileSync(join(out, "report.json"), JSON.stringify({ base, results, problems, notes }, null, 2));
  const shots = results.reduce((n, r) => n + r.screenshots.length, 0);
  console.log(`verify: ${results.length} visits, ${shots} screenshots in ${out}`);
  for (const n of notes) console.log(`  note: ${n}`);
  for (const p of problems) console.error(`  FAIL: ${p}`);
  console.log(problems.length ? `verify: FAILED (${problems.length} problem${problems.length === 1 ? "" : "s"})` : "verify: OK, no console errors or 5xx responses");
  process.exit(problems.length ? 1 : 0);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main().catch((e) => { console.error(e); process.exit(2); });
