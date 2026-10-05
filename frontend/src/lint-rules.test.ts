// The lint rules in eslint.config.js that keep the web app on its paved paths (lib/act.ts, lib/api.ts): each has code it
// must flag and code it must leave alone. The code is linted with the real config, as the file it says it is, because where a rule applies is part of the rule.
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../..", import.meta.url));
const eslint = new ESLint({ cwd: root, overrideConfigFile: `${root}frontend/eslint.config.js` });

/** The rules that flag `code`, one entry per finding, when it's linted as `file` (relative to the repository root). */
async function flagged(code: string, file = "frontend/src/lib/example.ts"): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: `${root}${file}` });
  return result.messages.map((m) => m.ruleId ?? `parse error: ${m.message}`);
}

describe("no (x as Error).message", () => {
  it("flags the cast", async () => {
    expect(await flagged("export const m = (e as Error).message;")).toEqual(["no-restricted-syntax"]);
  });
  it("leaves errMsg and other uses of a cast alone", async () => {
    expect(await flagged('import { errMsg } from "./act";\nexport const m = errMsg(new Error("x"));')).toEqual([]);
    expect(await flagged("export const n = (e as Error).name;")).toEqual([]);
    expect(await flagged("export const m = (e as { message: string }).message;")).toEqual([]);
  });
});

describe("no fetch() outside lib/api.ts", () => {
  it("flags fetch, window.fetch and globalThis.fetch", async () => {
    expect(await flagged('export const r = fetch("/api/x");')).toEqual(["no-restricted-syntax"]);
    expect(await flagged('export const r = window.fetch("/api/x");')).toEqual(["no-restricted-syntax"]);
    expect(await flagged('export const r = globalThis.fetch("/api/x");')).toEqual(["no-restricted-syntax"]);
  });
  it("flags it in a component's script too", async () => {
    expect(await flagged('<script lang="ts">\n  fetch("/api/x");\n</script>\n', "frontend/src/Example.svelte")).toEqual(["no-restricted-syntax"]);
  });
  it("leaves api() alone, and lib/api.ts itself", async () => {
    expect(await flagged('import { api } from "./api";\nexport const r = api("/api/x");')).toEqual([]);
    expect(await flagged('export const r = fetch("/api/x");', "frontend/src/lib/api.ts")).toEqual([]);
  });
});

describe("no .catch(() => {}) without a reason", () => {
  it("flags an empty handler", async () => {
    expect(await flagged("export const p = work().catch(() => {});")).toEqual(["waypoint/no-silent-catch"]);
    expect(await flagged("export const p = work().catch(function () {});")).toEqual(["waypoint/no-silent-catch"]);
  });
  it("leaves a handler that says why, or does something", async () => {
    expect(await flagged("export const p = work().catch(() => { /* a failed preload only costs time */ });")).toEqual([]);
    expect(await flagged("export const p = work().catch(() => {\n  // the next check corrects it\n});")).toEqual([]);
    expect(await flagged("export const p = work().catch((e) => report(e));")).toEqual([]);
  });
});

describe("no browser storage", () => {
  it("flags localStorage, sessionStorage and indexedDB", async () => {
    expect(await flagged('localStorage.setItem("k", "v");')).toEqual(["no-restricted-syntax"]);
    expect(await flagged('export const v = window.sessionStorage.getItem("k");')).toEqual(["no-restricted-syntax"]);
    expect(await flagged('export const r = indexedDB.open("w");')).toEqual(["no-restricted-syntax"]);
  });
  it("leaves state kept in memory alone", async () => {
    expect(await flagged("export const kept = new Map<string, string>();")).toEqual([]);
  });
});

describe("no console", () => {
  it("flags console.log, info and debug in the web app", async () => {
    expect(await flagged('console.log("trip", 1);')).toEqual(["no-console"]);
    expect(await flagged('console.info("trip", 1);')).toEqual(["no-console"]);
  });
  it("leaves errors alone", async () => {
    expect(await flagged("console.error(new Error('x'));")).toEqual([]);
  });
});
