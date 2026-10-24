import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "../..");
const dir = join(root, "artifacts", "control-smoke");
const env = { ...process.env, WAYPOINT_CONTROL_DIR: dir };

function control(...args) { return controlWith(env, ...args); }

function controlWith(withEnv, ...args) {
  console.log(`$ tools/control ${args.join(" ")}`);
  const r = spawnSync(process.execPath, [join(here, "control.mjs"), ...args], { cwd: root, env: withEnv, encoding: "utf8", timeout: 300000 });
  const out = (r.stdout ?? "").trim();
  console.log(out.length > 1500 ? `${out.slice(0, 1500)}…` : out);
  const parse = () => { try { return JSON.parse(out); } catch { return null; } };
  return { code: r.status, json: parse(), out };
}

function expect(ok, what) {
  if (ok) { console.log(`  ok: ${what}`); return; }
  console.error(`  FAIL: ${what}`);
  control("stop");
  process.exit(1);
}

const pngWidth = (file) => readFileSync(file).readUInt32BE(16);

rmSync(dir, { recursive: true, force: true });
let r = control("doctor");
expect(r.json && r.json.checks.filter((c) => !c.ok && c.name !== "machine load").length === 0, "doctor: every check passes (the machine's load aside)");

const fake = join(dir, "fake-browsers");
mkdirSync(join(fake, "chromium-0", "chrome-linux"), { recursive: true });
writeFileSync(join(fake, "chromium-0", "chrome-linux", "chrome"), "#!/bin/sh\necho 'not a browser' >&2\nexit 1\n", { mode: 0o755 });
r = controlWith({ ...env, PLAYWRIGHT_BROWSERS_PATH: fake }, "start", "--anyway");
expect(r.code === 1 && r.json?.error?.code === "start_failed" && !r.json.error.message.includes("its process ended") && !existsSync(join(dir, "state.json")),
  "a start that fails reports the session's own error, and leaves no state behind");
rmSync(fake, { recursive: true, force: true });

r = control("start", "--anyway");
expect(r.code === 0 && r.json?.ok && r.json.url.startsWith("http://127.0.0.1:"), "start: a session on a loopback demo server");
expect(r.json.clock.browser.startsWith("Mon Jun 15 2026 12:00:00"), "the browser's clock is at the frozen moment, noon");

r = control("start");
expect(r.code === 1 && r.json?.error?.code === "already_running", "a second start is refused, and says what to do");

r = control("info");
expect(r.json?.ok && r.json.viewport.width === 440 && r.json.route === "/#upcoming", "info: the phone width, on Upcoming");

r = control("snapshot", "--text");
expect(r.code === 0 && r.out.includes('heading "Upcoming" [level=1]'), "snapshot: the accessibility tree, with the page's heading");

r = control("offline");
expect(r.code === 0 && r.json?.ok && r.json.server.startsWith("http://localhost:"), "offline: set up on localhost, as make verify does before each page");
control("goto", "upcoming");
r = control("screenshot");
const shot = r.json?.path && join(root, r.json.path);
expect(r.json?.ok && existsSync(shot) && pngWidth(shot) === 440, "screenshot: a full-page PNG at the phone's width, under artifacts/");
const baseline = join(root, "docs", "src", "assets", "screenshots", "upcoming-phone.png");
console.log(`  note: ${readFileSync(shot).equals(readFileSync(baseline)) ? "byte for byte the same as" : "differs from (another Chromium build?)"} docs/src/assets/screenshots/upcoming-phone.png`);

r = control("click", "button", "Definitely not on the page", "--timeout", "500");
expect(r.code === 1 && r.json?.error?.code === "no_match" && r.json.error.hint.includes("snapshot"), "a click on nothing fails with what to do instead");

r = control("goto", "https://example.com");
expect(r.code === 1 && r.json?.error?.code === "refused", "goto anywhere but its own server is refused");

r = control("eval", "() => fetch('/api/control-smoke', { method: 'POST' }).then((r) => r.status)");
expect(r.code === 1 && r.json?.error?.code === "not_read_only", "eval is read-only without --write: a POST is blocked, and said so");
control("console");
control("network");

r = control("flow", "open-trip", "--viewport", "desktop");
expect(r.code === 0 && r.json?.steps?.every((s) => s.ok) && r.json.files.length === 2, "flow: open-trip passes, step by step, with its 2 images");

r = control("flow", "offline-trip", "--viewport", "desktop");
expect(r.code === 0 && r.json?.steps?.every((s) => s.ok), "flow: offline-trip passes after offline: it runs in a browser of its own");

r = control("flow", "more-menu", "--viewport", "desktop");
expect(r.code === 1 && r.json?.error?.code === "flow_failed" && r.json.steps?.some((s) => !s.ok && s.error)
  && r.json.files?.some((f) => f.includes("-FAILED-")), "a failed flow says which step failed, why, and where its -FAILED- image is");

r = control("reset", "--dry-run");
expect(r.json?.dryRun === true, "reset --dry-run says what it would do");
r = control("reset");
expect(r.json?.ok && r.json.reset, "reset: fresh data on a new server");

const pid = JSON.parse(readFileSync(join(dir, "state.json"), "utf8")).pid;
r = control("stop");
expect(r.json?.ok && r.json.stopped, "stop");
let alive = true;
try { process.kill(pid, 0); } catch { alive = false; }
expect(!alive && !existsSync(join(dir, "state.json")) && !existsSync(join(dir, `session-${pid}`)), "nothing left: the daemon gone, its state and data removed");
r = control("doctor");
expect(r.json?.checks.find((c) => c.name === "leftover processes")?.ok, "doctor finds no leftover processes");
console.log("control-smoke: passed");
