import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { visualizer } from "rollup-plugin-visualizer";
import path from "node:path";

// /_dl/* only exists inside the decryption Service Worker. Caddy answers a
// plain 404 when such a request reaches it (the worker didn't intercept:
// hard reload, or the browser's download manager retrying outside any
// page); Vite's SPA fallback would instead serve index.html as a 200,
// which a download manager happily saves as a 1 kB "completed" file.
// Match Caddy so dev shows the same failure prod would.
// Prefixes Caddy reverse-proxies to Django in production (caddy/Caddyfile).
// In prod the browser therefore talks to a single origin: Caddy serves the
// built frontend and forwards these to the backend. Keeping the dev server
// on the same routing is not a convenience -- without it the app is split
// over two ports, and two things that matter break:
//
//   * the backend sees the API port's host (``localhost``) whatever domain
//     the browser is actually on, so per-domain configuration can never be
//     exercised in dev, and the OIDC redirect_uri points at the API port;
//   * the session cookie belongs to the API's host, which the page is not
//     served from, so a second domain looks permanently logged out.
//
// The Django admin stays on the backend's own port in dev; Caddy's admin
// rules (IP allowlist, trailing-slash redirect) have no equivalent here.
// Kept in sync with the Caddyfile by caddy/Caddyfile.test.ts.
export const BACKEND_PREFIXES = ["/api", "/__heartbeat__", "/static"];

export const BACKEND_PREFIXES_NOT_PROXIED_IN_DEV = [
  "/{$DJANGO_ADMIN_URL:admin}",
];

const backendProxy = () => {
  // Same variable name as the Caddyfile's target. Default: the compose
  // service, since the dev server runs in a container next to it.
  const server =
    process.env.TRANSFERS_FRONTEND_BACKEND_SERVER || "backend-dev:8000";
  return Object.fromEntries(
    BACKEND_PREFIXES.map((prefix) => [
      prefix,
      {
        target: `http://${server}`,
        // Pass the browser's Host through untouched, as Caddy does: it is
        // what the backend resolves its per-domain configuration from.
        changeOrigin: false,
      },
    ]),
  );
};

const noSpaFallbackForDownloads = (): Plugin => ({
  name: "transfers:no-spa-fallback-for-downloads",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url?.startsWith("/_dl/")) {
        res.statusCode = 404;
        res.setHeader("Content-Type", "text/plain; charset=utf-8");
        res.end(
          "Not found: /_dl/ URLs are served by the decryption Service Worker.",
        );
        return;
      }
      next();
    });
  },
});

export default defineConfig({
  plugins: [
    // See ./tsr.config.json for tanstackRouter config
    tanstackRouter(),
    react(),
    noSpaFallbackForDownloads(),
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
    // Forward the backend's prefixes, so dev is single-origin like prod.
    proxy: backendProxy(),
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
