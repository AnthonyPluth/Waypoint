import { codecovVitePlugin } from "@codecov/vite-plugin";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { svelteTesting } from "@testing-library/svelte/vite";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/",
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
  test: {
    env: { TZ: "America/New_York" },
    setupFiles: ["src/test/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,svelte}"],
      exclude: ["src/**/*.test.ts", "src/**/*.d.ts", "src/main.ts", "src/test/**"],
      reporter: ["text-summary", "lcovonly"],
      thresholds: { statements: 85, lines: 85, functions: 80, branches: 75 },
    },
  },
  server: {
    proxy: Object.fromEntries(["/api", "/auth", "/fonts", "/logo.svg", "/logo-180.png", "/sw.js", "/manifest.webmanifest", "/icon-192.png"].map((p) => [p, "http://127.0.0.1:8765"])),
  },
});
