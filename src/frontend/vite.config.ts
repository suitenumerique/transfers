import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { visualizer } from "rollup-plugin-visualizer";
import path from "node:path";

export default defineConfig({
  plugins: [
    // See ./tsr.config.json for tanstackRouter config
    tanstackRouter(),
    react(),
    // Opt-in bundle analyzer: emits bundle-stats.json next to the project
    // root when ANALYZE=1. Consumed by `npm run analyze` (see Makefile).
    process.env.ANALYZE === "1" &&
      (visualizer({
        filename: "bundle-stats.json",
        template: "raw-data",
        gzipSize: true,
      }) as Plugin),
  ].filter(Boolean) as Plugin[],
  server: {
    host: "0.0.0.0",
    port: 3000,
    strictPort: true,
  },
  preview: {
    host: "0.0.0.0",
    port: 3000,
    strictPort: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        // Vite 8's default sass compiler no longer forwards Node's module
        // resolver into ``@use`` — importing ``@gouvfr-lasuite/ui-kit/style``
        // and the other npm-scoped SCSS packages fails silently to an empty
        // CSS blob, leaving the whole app unstyled. Adding ``node_modules``
        // to sass ``loadPaths`` restores the pre-8 behaviour so bare
        // specifiers resolve.
        loadPaths: [path.resolve(__dirname, "./node_modules")],
      },
    },
  },
  // App env vars are read via `import.meta.env.NEXT_PUBLIC_*`. envPrefix
  // tells Vite which env vars to expose to client code at build time.
  envPrefix: "NEXT_PUBLIC_",
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
