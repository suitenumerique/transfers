import { defineConfig, devices } from "@playwright/test";

// Runs against the stack of compose.e2e.yaml (see README.md). The URLs are
// the ones the app itself hands out, so they are fixed, not configurable.
export const FRONTEND_URL = "http://localhost:7980";
// The same frontend, reached on a second name, so the per-domain
// configuration has two domains to tell apart (env.d/e2e/backend.e2e).
// Browsers resolve *.localhost to loopback themselves, and the runner's
// forwarder listens there, so this needs no DNS and no /etc/hosts.
export const OPERATOR_URL = "http://opsn1.localhost:7980";
export const API_URL = "http://localhost:7981";
export const MAIL_URL = "http://localhost:7984";

const isCI = Boolean(process.env.CI);

// Reports, traces and saved sessions (see compose.e2e.yaml).
export const OUTPUT_DIR = process.env.E2E_OUTPUT ?? ".";

export default defineConfig({
  testDir: "./tests",
  outputDir: `${OUTPUT_DIR}/test-results`,
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  // Two, not four. The API is same-origin, so every request goes through the
  // Vite dev server, which is also transforming modules for each freshly
  // opened context -- one Node process doing both. At four workers a cold
  // page load starved the API call that page then made, and the download
  // page sat on its spinner past any sane timeout: the same spec took 6s
  // alone and 46s four-up. Production does not have this shape (Caddy serves
  // a built bundle and proxies), so this is the dev server's limit, not the
  // app's.
  workers: 2,
  // Uploads go through encryption and S3; the Vite dev server compiles
  // routes on first visit.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: `${OUTPUT_DIR}/playwright-report` }],
  ],
  use: {
    baseURL: FRONTEND_URL,
    locale: "en-US",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    acceptDownloads: true,
  },
  projects: [
    // Signs each dev user in once and saves the session for the tests.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],
});
