import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync, readlinkSync, rmSync } from "node:fs";
import { get } from "node:http";
import { createServer } from "node:net";

export const freePort = () => new Promise((resolve, reject) => {
  const probe = createServer();
  probe.on("error", reject);
  probe.listen(0, "127.0.0.1", () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
});

export const answers = (port, path = "/healthz") => new Promise((resolve) => {
  const req = get({ host: "127.0.0.1", port, path, timeout: 2000 }, (res) => { res.resume(); resolve(res.statusCode >= 200 && res.statusCode < 400); });
  req.on("error", () => resolve(false));
  req.on("timeout", () => { req.destroy(); resolve(false); });
});

export function listensOn(pid, port, proc = "/proc") {
  if (!existsSync(`${proc}/net/tcp`)) return null;
  let inodes;
  try {
    inodes = new Set(["tcp", "tcp6"].flatMap((f) => {
      try { return readFileSync(`${proc}/net/${f}`, "utf8").split("\n").slice(1); } catch { return []; }
    }).map((line) => line.trim().split(/\s+/)).filter((c) => c.length > 9 && c[3] === "0A" && parseInt(c[1].split(":")[1], 16) === port)
      .map((c) => `socket:[${c[9]}]`));
    if (!inodes.size) return false;
    return readdirSync(`${proc}/${pid}/fd`).some((fd) => {
      try { return inodes.has(readlinkSync(`${proc}/${pid}/fd/${fd}`)); } catch { return false; }
    });
  } catch {
    return false;
  }
}

const exited = (proc) => new Promise((resolve) => { if (proc.exitCode !== null || proc.signalCode !== null) resolve(); else proc.once("exit", () => resolve()); });
const tail = (file) => { try { return readFileSync(file, "utf8").slice(-2000); } catch { return ""; } };

async function stopServer(proc, folder, grace = 10000) {
  if (proc.exitCode === null && proc.signalCode === null) {
    proc.kill("SIGTERM");
    let timer;
    await Promise.race([exited(proc), new Promise((r) => { timer = setTimeout(r, grace); })]);
    clearTimeout(timer);
    if (proc.exitCode === null && proc.signalCode === null) { proc.kill("SIGKILL"); await exited(proc); }
  }
  rmSync(folder, { recursive: true, force: true });
}

export async function startServer({ command, folder, timeout = 60000, tries = 3, cwd, poll = 200, port: pick = freePort }) {
  let why = "";
  for (let attempt = 1; attempt <= tries; attempt++) {
    const port = await pick();
    const dir = `${folder}-${attempt}`;
    const [program, ...args] = command(port, dir);
    const proc = spawn(program, args, { cwd, stdio: "ignore" });
    let failed = null;
    proc.once("error", (e) => { failed = e.message; });
    const end = Date.now() + timeout;
    for (;;) {
      if (failed || proc.exitCode !== null || proc.signalCode !== null) break;
      if (await answers(port) && listensOn(proc.pid, port) !== false) return { port, stop: () => stopServer(proc, dir) };
      if (Date.now() > end) {
        const log = tail(`${dir}/server.log`);
        await stopServer(proc, dir);
        throw new Error(`the demo server wasn't answering on port ${port} after ${Math.round(timeout / 1000)} seconds\n${log}`);
      }
      await new Promise((r) => setTimeout(r, poll));
    }
    if (!failed) await exited(proc);
    why = failed ? `it couldn't start (${failed})` : `it exited with ${proc.exitCode ?? proc.signalCode} before it answered`;
    const log = tail(`${dir}/server.log`);
    rmSync(dir, { recursive: true, force: true });
    if (failed || attempt === tries) throw new Error(`the demo server didn't start: ${why}${tries > 1 && !failed ? ` (${attempt} tries)` : ""}\n${log}`);
  }
  throw new Error(`the demo server didn't start: ${why}`);
}
