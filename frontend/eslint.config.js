// Run with `npm run lint`, which lints from the repository root so this one config also covers the server's service
// worker: plain JavaScript with no build step or package of its own. Paths are relative
// to the repository root for that reason.
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";

const FRONTEND = "frontend/**/*.{js,ts,svelte}";

// Waypoint's own rules: the paved paths (lib/act.ts, lib/api.ts) that the web app uses for what would
// otherwise be copied page by page. Fix a finding by using the path; where a use is right for a reason, put
// `// eslint-disable-next-line no-restricted-syntax -- <why>` on it. frontend/src/lint-rules.test.ts holds the
// examples that prove each rule fires, and stays quiet on the right code.
const RESTRICTED = {
  errorCast: {
    selector: "MemberExpression[property.name='message'][object.type='TSAsExpression'][object.typeAnnotation.typeName.name='Error']",
    message: "Don't cast to Error to read .message: errMsg(e) from lib/act.ts says what was thrown, whatever it is.",
  },
  fetch: {
    selector: "CallExpression[callee.name='fetch'], CallExpression[callee.object.name=/^(window|globalThis|self)$/][callee.property.name='fetch']",
    message: "Call the server through api() in lib/api.ts (it sends the cookies and headers, and turns a failure into an Error); fetch() belongs only there.",
  },
};
const restrict = (...names) => ["error", ...names.map((n) => RESTRICTED[n])];

// `.catch(() => {})` throws a failure away without saying why; a comment inside the braces says why that's right.
const waypoint = {
  rules: {
    "no-silent-catch": {
      meta: { type: "suggestion", schema: [], messages: { silent: "`.catch(() => {})` swallows the failure without a reason: say in a comment inside why nobody needs to know." } },
      create(context) {
        return {
          CallExpression(node) {
            const { callee, arguments: args } = node;
            const handler = args[0];
            if (callee.type !== "MemberExpression" || callee.property.name !== "catch" || !handler) return;
            if (handler.type !== "ArrowFunctionExpression" && handler.type !== "FunctionExpression") return;
            const body = handler.body;
            if (handler.params.length === 0 && body.type === "BlockStatement" && body.body.length === 0
                && context.sourceCode.getCommentsInside(body).length === 0) {
              context.report({ node: handler, messageId: "silent" });
            }
          },
        };
      },
    },
  },
};

export default defineConfig(
  // The web app builds into waypoint/static/app.
  { ignores: ["waypoint/static/app/**", "**/node_modules/**"] },
  js.configs.recommended,
  ts.configs.recommended,
  // The Svelte rules only for the web app: one of them crashes on classic (non-module) scripts.
  ...svelte.configs.recommended.map((c) => (c.files ? c : { ...c, files: [FRONTEND] })),
  {
    files: [FRONTEND],
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      // `{" · "}` and `{" "}` are deliberate: they keep a separator's spaces next to an {#if} that would trim them.
      "svelte/no-useless-mustaches": "off",
      // It flags every Date, Set and URLSearchParams in a Svelte file, but ours are throwaway locals or memos kept
      // non-reactive on purpose; reactive state here is replaced, not mutated in place.
      "svelte/prefer-svelte-reactivity": "off",
      "no-restricted-syntax": restrict("errorCast", "fetch"),
      "waypoint/no-silent-catch": "error",
    },
    plugins: { waypoint },
  },
  // lib/api.ts is the one place that calls fetch.
  { files: ["frontend/src/lib/api.ts"], rules: { "no-restricted-syntax": restrict("errorCast") } },
  {
    rules: {
      // A leading underscore marks a name that's unused on purpose (a page's unused route props, `catch (_)`).
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
    files: ["waypoint/static/**/*.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.serviceworker } },
  },
);
