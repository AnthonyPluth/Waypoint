import { chromium } from "@playwright/test";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const VIEWPORTS = { phone: { width: 390, height: 844 }, tablet: { width: 768, height: 1024 }, desktop: { width: 1280, height: 800 } };
export const PAGES = ["upcoming", "trips", "stats", "people", "review", "settings", "oauth-approve"];
const OWN_PAGES = ["oauth-approve"];
export const SCHEMES = ["light", "dark"];

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

export const screenshotFiles = (name, viewport) => ({ full: `${name}-${viewport}.png`, top: `${name}-${viewport}-top.png` });

const ACTIONS = { goto: "string", click: "string", select: "object", fill: "object", press: "object", upload: "object", scroll_to: "string", wait_for: "string", expect_text: "object", screenshot: "string" };
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

async function runStep(page, step, shot) {
  const timeout = step.timeout ?? 10000;
  if ("goto" in step) {
    await page.goto(step.goto.startsWith("#") ? `${page.url().split("#")[0]}${step.goto}` : step.goto);
  } else if ("click" in step) {
    await page.locator(step.click).first().click({ timeout });
  } else if ("select" in step) {
    await page.locator(step.select.selector).first().selectOption({ index: step.select.index }, { timeout });
  } else if ("fill" in step) {
    await page.locator(step.fill.selector).first().fill(step.fill.text, { timeout });
  } else if ("press" in step) {
    await page.locator(step.press.selector).first().press(step.press.key, { timeout });
  } else if ("upload" in step) {
    await page.locator(step.upload.selector).first().setInputFiles(join(REPO, step.upload.file), { timeout });
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
  const problems = [];
  const notes = [];
  const results = [];
  let approveUrl = "";
  try { approveUrl = await seedAssistants(browser, base); }
  catch (e) { problems.push(`seeding the demo assistants: ${String(e.message).split("\n")[0]}`); }

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
      await shot(`${label.replace(/\W+/g, "-")}-FAILED`).catch(() => {});
    }
    for (const c of consoleErrors) problems.push(`${where}: console error: ${c.slice(0, 300)}`);
    results.push({ label, viewport, screenshots: files, consoleErrors });
    await ctx.close();
  }

  for (const name of pages) {
    for (const viewport of Object.keys(VIEWPORTS)) {
      await visit(name, viewport, async (page, shot) => {
        if (OWN_PAGES.includes(name)) {
          if (!approveUrl) throw new Error("no approval page: seeding the demo assistants failed");
          await page.goto(approveUrl, { waitUntil: "networkidle" });
          await page.locator("button[value=allow]").waitFor({ timeout: 10000 });
        } else await page.goto(`${base}/#${name}`, { waitUntil: "networkidle" });
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
