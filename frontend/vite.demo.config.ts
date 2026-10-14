import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  root:path.resolve("demo"),
  base:"./",
  publicDir:false,
  plugins:[{
    name:"standalone-demo",
    enforce:"pre",
    resolveId(source,importer) {
      if (source === "$lib/api" || (source === "./api" && importer?.includes("/src/lib/"))) return path.resolve("demo/api.ts");
      if (source === "$lib/offline.svelte" || (source === "./offline.svelte" && importer?.includes("/src/lib/"))) return path.resolve("demo/offline.svelte.ts");
    },
    generateBundle() {
      const forbidden = [...this.getModuleIds()].filter(id=>/\/src\/(?:main\.ts|lib\/(?:api\.ts|offline\.svelte\.ts))$/.test(id));
      if (forbidden.length) this.error(`Runtime transport or bootstrap included in static demo: ${forbidden.join(", ")}`);
    },
    transform(code,id) {
      if (id.endsWith("/src/lib/components/Logo.svelte")) return code.replace('<script lang="ts">', '<script lang="ts">\n  import demoLogo from "../../../../waypoint/static/logo.svg";').replace('src="/logo.svg"', 'src={demoLogo}');
      if (id.endsWith("/src/app.css")) return '@source "./";\n' + code.replace('/fonts/Geist-Variable.woff2','../../waypoint/static/fonts/Geist-Variable.woff2');
    }
  },tailwindcss(),svelte()],
  resolve:{alias:[{find:/^\$lib\/api$/,replacement:path.resolve("demo/api.ts")},{find:/^\$lib\/offline\.svelte$/,replacement:path.resolve("demo/offline.svelte.ts")},{find:"$lib",replacement:path.resolve("src/lib")}]},
  build:{outDir:path.resolve("demo-dist"),emptyOutDir:true,sourcemap:false},
});
