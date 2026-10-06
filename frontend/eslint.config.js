import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";

const FRONTEND = "frontend/**/*.{js,ts,svelte}";

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

const waypoint = {
  rules: {
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
  js.configs.recommended,
  ts.configs.recommended,
  ...svelte.configs.recommended.map((c) => (c.files ? c : { ...c, files: [FRONTEND] })),
  {
    files: [FRONTEND],
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      "svelte/no-useless-mustaches": "off",
      "svelte/prefer-svelte-reactivity": "off",
      "no-restricted-syntax": restrict("errorCast", "fetch", "storage"),
      "waypoint/no-silent-catch": "error",
      "no-console": ["error", { allow: ["error", "warn"] }],
    },
    plugins: { waypoint },
  },
  { files: ["frontend/src/lib/api.ts"], rules: { "no-restricted-syntax": restrict("errorCast", "storage") } },
  {
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
