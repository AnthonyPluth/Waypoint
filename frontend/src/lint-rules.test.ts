import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../..", import.meta.url));
const eslint = new ESLint({ cwd: root, overrideConfigFile: `${root}frontend/eslint.config.js` });

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

describe("no .catch(() => {})", () => {
  it("flags an empty handler", async () => {
    expect(await flagged("export const p = work().catch(() => {});")).toEqual(["waypoint/no-silent-catch"]);
    expect(await flagged("export const p = work().catch(function () {});")).toEqual(["waypoint/no-silent-catch"]);
    expect(await flagged("export const p = work().catch(() => { /* why */ });")).toEqual(["waypoint/no-silent-catch", "waypoint/no-comments"]);
  });
  it("leaves a handler that does something, and ignoreFailure", async () => {
    expect(await flagged("export const p = work().catch((e) => report(e));")).toEqual([]);
    expect(await flagged('import { ignoreFailure } from "./act";\nexport const p = work().catch(ignoreFailure);')).toEqual([]);
  });
});

describe("no comments", () => {
  it("flags line and block comments, in a component too", async () => {
    expect(await flagged("// says what the next line does\nexport const n = 1;")).toEqual(["waypoint/no-comments"]);
    expect(await flagged("export const n = 1; /* trailing */")).toEqual(["waypoint/no-comments"]);
    expect(await flagged('<script lang="ts">\n  // a note\n  export const n = 1;\n</script>\n', "frontend/src/Example.svelte")).toEqual(["waypoint/no-comments"]);
  });
  it("leaves the tools' directives and strings that look like comments alone", async () => {
    expect(await flagged("// @ts-expect-error: the point of the test\nexport const n: string = 1;")).toEqual([]);
    expect(await flagged('// @vitest-' + 'environment jsdom\nexport const u = "https://example.com/a//b";')).toEqual([]);
    expect(await flagged("// svelte-ignore state_referenced_locally\nexport const n = 1;")).toEqual([]);
    expect(await flagged('/// <reference types="node" />\nexport const n = 1;')).toEqual([]);
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

describe("the app is dark only", () => {
  it("flags a dark: variant in a string, a template and a component's class", async () => {
    expect(await flagged('export const c = "bg-card dark:bg-secondary";')).toEqual(["no-restricted-syntax"]);
    expect(await flagged("export const c = `border dark:border-input`;")).toEqual(["no-restricted-syntax"]);
    expect(await flagged('<div class="flex dark:bg-secondary"></div>\n', "frontend/src/Example.svelte")).toEqual(["no-restricted-syntax"]);
  });
  it("flags a prefers-color-scheme query", async () => {
    expect(await flagged('export const q = "(prefers-color-scheme: light)";')).toEqual(["no-restricted-syntax"]);
  });
  it("leaves other variants and plain words alone", async () => {
    expect(await flagged('export const c = "bg-secondary hover:bg-accent focus-visible:ring-ring";')).toEqual([]);
    expect(await flagged('export const t = "Dark roast, no variant: here";')).toEqual([]);
  });
});
