import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";

const FRONTEND = "frontend/**/*.{js,ts,svelte}";
const CODE = ["**/*.{js,mjs,cjs,ts,tsx,mts,cts,svelte}"];

const RESTRICTED = {
  errorCast: {
    selector: "MemberExpression[property.name='message'][object.type='TSAsExpression'][object.typeAnnotation.typeName.name='Error']",
    message: "Don't cast to Error to read .message: errMsg(e) from lib/act.ts says what was thrown, whatever it is.",
  },
  fetch: {
    selector: "CallExpression[callee.name='fetch'], CallExpression[callee.object.name=/^(window|globalThis|self)$/][callee.property.name='fetch']",
    message: "Call the server through api() in lib/api.ts (it sends the cookies and headers, and turns a failure into an Error); fetch() belongs only there.",
  },
  storage: {
    selector: "Identifier[name=/^(localStorage|sessionStorage|indexedDB)$/]",
    message: "Browser storage outlives sign-out and is readable by anything on the device: keep trips, names, codes and loyalty numbers on the server (AGENTS.md, \"Waypoint's promises\").",
  },
};
const restrict = (...names) => ["error", ...names.map((n) => RESTRICTED[n])];

const luminance = (hex) => {
  const full = hex.length === 3 ? [...hex].map((c) => c + c).join("") : hex;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const LIGHT_SURFACE = 0.6;

const textParser = {
  parseForESLint(code) {
    const globalScope = { set: new Map(), variables: [], through: [], references: [], childScopes: [] };
    return {
      ast: { type: "Program", body: [], comments: [], tokens: [], sourceType: "module", range: [0, code.length], loc: { start: { line: 1, column: 0 }, end: { line: 1, column: 0 } } },
      scopeManager: {
        scopes: [globalScope],
        globalScope,
        addGlobals(names) { for (const name of names) if (!globalScope.set.has(name)) globalScope.set.set(name, { name }); },
        acquire: () => null,
        getDeclaredVariables: () => [],
      },
      visitorKeys: { Program: [] },
    };
  },
};

const waypoint = {
  rules: {
    "no-light-theme": {
      meta: {
        type: "problem",
        schema: [],
        messages: {
          variant: "Waypoint is dark only: `dark:` switches on a light theme that has no palette. Style it dark and drop the variant.",
          scheme: "Waypoint is dark only: don’t handle prefers-color-scheme or declare `color-scheme: light` — there is nothing to switch to.",
          palette: "`--{name}` is a light surface, and Waypoint’s surfaces are dark (the light palette was removed in issue #131). Ink and foreground tokens may be light.",
          white: "Waypoint is dark only: `bg-white` paints a light surface. Use bg-card, bg-secondary or the status tokens in app.css.",
        },
      },
      create(context) {
        const source = context.sourceCode;
        const report = (index, messageId, data) => context.report({ loc: source.getLocFromIndex(index), messageId, data });
        return {
          Program() {
            const text = source.getText();
            for (const m of text.matchAll(/(?<![\w-])dark:/g)) report(m.index, "variant");
            for (const m of text.matchAll(/prefers-color-scheme/g)) report(m.index, "scheme");
            for (const m of text.matchAll(/color-scheme\s*:\s*light\b/g)) report(m.index, "scheme");
            for (const m of text.matchAll(/(?<![\w-])bg-white(?![\w/-])/g)) report(m.index, "white");
            for (const m of text.matchAll(/(?<name>--[a-z0-9-]+)\s*:\s*(?<value>[^;}\n]+)/gi)) {
              if (/(^|-)(ink|foreground)$/.test(m.groups.name)) continue;
              const start = m.index + m[0].length - m.groups.value.length;
              for (const h of m.groups.value.matchAll(/#([0-9a-f]{3}|[0-9a-f]{6})(?![0-9a-f])/gi)) {
                if (luminance(h[1]) >= LIGHT_SURFACE) report(start + h.index, "palette", { name: m.groups.name });
              }
            }
          },
        };
      },
    },
    "no-silent-catch": {
      meta: { type: "suggestion", schema: [], messages: { silent: "`.catch(() => {})` swallows the failure: pass `ignoreFailure` from lib/act.ts, which says so by name." } },
      create(context) {
        return {
          CallExpression(node) {
            const { callee, arguments: args } = node;
            const handler = args[0];
            if (callee.type !== "MemberExpression" || callee.property.name !== "catch" || !handler) return;
            if (handler.type !== "ArrowFunctionExpression" && handler.type !== "FunctionExpression") return;
            const body = handler.body;
            if (handler.params.length === 0 && body.type === "BlockStatement" && body.body.length === 0) {
              context.report({ node: handler, messageId: "silent" });
            }
          },
        };
      },
    },
    "no-comments": {
      meta: { type: "problem", schema: [], messages: { comment: "No comments: name things so the code says it, and put the why in the commit message or the docs. Tool directives (eslint-, @ts-, svelte-ignore, @vitest-environment) are the exception." } },
      create(context) {
        const directive = /^\/?\s*(eslint-|@ts-|svelte-ignore|@vitest|<reference|istanbul|c8 |v8 ignore|prettier-ignore|global )/;
        return {
          Program() {
            for (const c of context.sourceCode.getAllComments()) {
              if (c.type === "Shebang" || directive.test(c.value)) continue;
              context.report({ loc: c.loc, messageId: "comment" });
            }
          },
        };
      },
    },
  },
};

export default defineConfig(
  { ignores: ["waypoint/static/app/**", "**/node_modules/**"] },
  { ...js.configs.recommended, files: CODE },
  ...ts.configs.recommended.map((c) => ({ ...c, files: c.files ?? CODE })),
  ...svelte.configs.recommended.map((c) => (c.files ? c : { ...c, files: [FRONTEND] })),
  {
    files: [FRONTEND],
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      "svelte/no-useless-mustaches": "off",
      "svelte/prefer-svelte-reactivity": "off",
      "no-restricted-syntax": restrict("errorCast", "fetch", "storage"),
      "waypoint/no-silent-catch": "error",
      "waypoint/no-light-theme": "error",
      "no-console": ["error", { allow: ["error", "warn"] }],
    },
    plugins: { waypoint },
  },
  { files: ["frontend/src/lib/api.ts"], rules: { "no-restricted-syntax": restrict("errorCast", "storage") } },
  {
    files: ["frontend/**/*.css", "frontend/index.html"],
    languageOptions: { parser: textParser },
    plugins: { waypoint },
    rules: { "waypoint/no-light-theme": "error" },
  },
  {
    files: ["frontend/eslint.config.js", "frontend/src/lint-rules.test.ts"],
    rules: { "waypoint/no-light-theme": "off" },
  },
  {
    files: CODE,
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", {
        argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_",
      }],
    },
  },
  {
    files: ["frontend/*.{js,ts}", "frontend/verify/*.mjs"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["frontend/**/*.svelte", "frontend/**/*.svelte.ts"],
    languageOptions: { parserOptions: { parser: ts.parser } },
  },
  {
    files: ["frontend/**/*.{js,mjs,ts,svelte}", "waypoint/static/**/*.js"],
    plugins: { waypoint },
    rules: { "waypoint/no-comments": "error" },
  },
  {
    files: ["waypoint/static/**/*.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.serviceworker } },
  },
);
