/// <reference types="vitest/config" />
import { codecovVitePlugin } from "@codecov/vite-plugin";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { svelteTesting } from "@testing-library/svelte/vite";
import path from "node:path";
import { defineConfig } from "vite";

// The built app goes to waypoint/static/app/, which the Python server serves at /.
// `npm run dev` serves it on its own port and passes API calls (and Waypoint's own files) through to Waypoint on 8765.
export default defineConfig({
  base: "/",
  // svelteTesting() makes Svelte resolve to its browser build under Vitest and unmounts components after each test.
  // codecovVitePlugin() sends the build's bundle sizes to Codecov, which tracks them and reports the change on pull
  // requests. Only in CI, where CODECOV_TOKEN is set; elsewhere it does nothing.
  plugins: [
    tailwindcss(),
    svelte(),
    svelteTesting(),
    codecovVitePlugin({
      enableBundleAnalysis: Boolean(process.env.CODECOV_TOKEN),
      bundleName: "waypoint-web",
      uploadToken: process.env.CODECOV_TOKEN,
      telemetry: false,
    }),
  ],
  resolve: { alias: { $lib: path.resolve("./src/lib") } },
  build: { outDir: "../waypoint/static/app", emptyOutDir: true, sourcemap: false },
  // `npm test` (Vitest) runs in one time zone, so date tests read the same everywhere. It's one behind UTC, where
  // the evening is already tomorrow: the case the date helpers are there for.
  test: {
    env: { TZ: "America/New_York" },
    // Logic tests run in Node (fast). A component test opts into the DOM with a `// @vitest-environment jsdom` first line.
    setupFiles: ["src/test/setup.ts"],
    // `npm run coverage`: how much of the web app the tests run, components included (so the number is honest about
    // what's untested). CI sends coverage/lcov.info to Codecov (the README's frontend badge).
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,svelte}"],
      exclude: ["src/**/*.test.ts", "src/**/*.d.ts", "src/main.ts", "src/test/**"],
      reporter: ["text-summary", "lcovonly"],
      // The floor (`make check` and CI fail below it): new screens come with tests that render them. Raise it as
      // coverage grows; lowering it needs a reason in the pull request.
      thresholds: { statements: 85, lines: 85, functions: 80, branches: 75 },
    },
  },
  server: {
    proxy: Object.fromEntries(["/api", "/auth", "/fonts", "/logo.svg", "/logo-180.png", "/sw.js", "/manifest.webmanifest", "/icon-192.png"].map((p) => [p, "http://127.0.0.1:8765"])),
  },
});
