// @vitest-environment node
//
// The CSP lives here, in the Caddyfile, while the widget URLs live in the
// backend config (LAGAUFRE_WIDGET_URL / LAGAUFRE_API_URL). Nothing ties the
// two together at runtime: when they drift, the browser blocks the widget
// and the only trace is a console violation. These tests pin the pairing.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const CADDYFILE = readFileSync(
  fileURLToPath(new URL("./Caddyfile", import.meta.url)),
  "utf8",
);

const SCRIPT_ORIGIN = "{$TRANSFERTS_FRONTEND_GAUFRE_SCRIPT_ORIGIN}";
const API_ORIGIN = "{$TRANSFERTS_FRONTEND_GAUFRE_API_ORIGIN}";

// Directive name -> its source list, read from the header itself so the test
// tracks the policy rather than a copy of it.
const policy = (): Record<string, string> => {
  const header = CADDYFILE.match(/Content-Security-Policy\s+"([^"]+)"/);
  if (!header) throw new Error("no Content-Security-Policy header in Caddyfile");
  return Object.fromEntries(
    header[1]
      .split(";")
      .map((directive) => directive.trim())
      .filter(Boolean)
      .map((directive) => {
        const [name, ...sources] = directive.split(/\s+/);
        return [name, sources.join(" ")];
      }),
  );
};

describe("Caddyfile CSP", () => {
  it("allows the LaGaufre script origin wherever the widget uses it", () => {
    const csp = policy();

    expect(csp["script-src"]).toContain(SCRIPT_ORIGIN);
    expect(csp["img-src"]).toContain(SCRIPT_ORIGIN);
    expect(csp["connect-src"]).toContain(SCRIPT_ORIGIN);
  });

  it("allows the LaGaufre API origin for both the fetch and the logos", () => {
    const csp = policy();

    // Regression: the services API was allowed in connect-src but not in
    // img-src, so the widget listed its services and every logo it points
    // at (/api/v1.0/servicelogo/...) was blocked.
    expect(csp["connect-src"]).toContain(API_ORIGIN);
    expect(csp["img-src"]).toContain(API_ORIGIN);
  });

  it("keeps deployment-specific hosts out of the policy", () => {
    // The widget is opt-in and configured per deployment. Hardcoding an
    // operator's hosts here ships them to every self-hosted instance.
    const csp = policy();

    expect(Object.values(csp).join(" ")).not.toMatch(/suite\.anct\.gouv\.fr/);
  });
});

describe("Caddyfile access log", () => {
  it("logs, since Caddy writes nothing unless asked", () => {
    // What Caddy answers on its own never reaches Django: an allowlist
    // refusal, an alias redirect, a static 404. Without this the only log is
    // the backend's, and those requests are invisible in it.
    expect(CADDYFILE).toMatch(/\blog \{/);
    expect(CADDYFILE).toMatch(/output stdout/);
    // console, not json: these lines are read by a human in journalctl.
    expect(CADDYFILE).toMatch(/format console/);
  });

  it("keeps the healthcheck probes out of the log", () => {
    // lprobe polls the container check on a loop and the platform polls the
    // backend's; logged, they bury the requests someone actually wants to
    // read, each one carrying the whole response header block.
    // Both spellings of each: Django answers the bare path and the slashed
    // one alike, and whoever polls picks either.
    const probes = CADDYFILE.match(/@probes path (.+)/)?.[1] ?? "";

    expect(probes.trim().split(/\s+/)).toEqual([
      "/__lbheartbeat__",
      "/__lbheartbeat__/",
      "/__heartbeat__",
      "/__heartbeat__/*",
    ]);
    expect(CADDYFILE).toMatch(/log_skip @probes/);
  });
});

describe("Caddyfile cache policy", () => {
  // A hashed URL names its own content, so it can be kept forever. Everything
  // else keeps its URL across deploys and must be revalidated — the
  // translations above all: they are fetched at runtime from a stable path,
  // so a cached catalogue outliving a deploy makes the app render the key it
  // cannot find, i.e. English text in a French page.
  it("caches hashed assets for a year and revalidates everything else", () => {
    expect(CADDYFILE).toMatch(/@immutable path \/assets\/\*/);
    expect(CADDYFILE).toMatch(
      /header @immutable Cache-Control "public, max-age=31536000, immutable"/,
    );
    expect(CADDYFILE).toMatch(/@revalidate not path \/assets\/\*/);
    expect(CADDYFILE).toMatch(/header @revalidate Cache-Control "no-cache"/);
  });

  it("leaves no stable-URL file cacheable without revalidation", () => {
    // The rule is deny-by-default on purpose: naming the exposed paths one by
    // one is what let /locales/ ship unprotected in the first place. Anything
    // added to public/ later is covered without a second thought.
    const immutablePaths = CADDYFILE.match(/@immutable path (\S+)/)?.[1];

    expect(immutablePaths).toBe("/assets/*");
  });
});

describe("Caddyfile client IP", () => {
  // The behaviour itself is exercised on the built image by
  // bin/smoke-test-front; this pins the wiring that makes it hold.
  it("hands the backend the client IP Caddy established, never the raw header", () => {
    const forwarded = CADDYFILE.match(/header_up X-Forwarded-For (\S+)/g) ?? [];

    expect(forwarded.length).toBeGreaterThan(0);
    for (const line of forwarded) {
      expect(line).toBe("header_up X-Forwarded-For {client_ip}");
    }
  });

  it("only trusts the proxies the deployment names, right to left", () => {
    expect(CADDYFILE).toMatch(
      /trusted_proxies static \{\$TRANSFERTS_FRONTEND_TRUSTED_PROXIES\}/,
    );
    expect(CADDYFILE).toMatch(/^\s*trusted_proxies_strict\s*$/m);
  });

  it("gates the admin URL on the allowlist, open by default", () => {
    expect(CADDYFILE).toMatch(
      /not client_ip \{\$DJANGO_ADMIN_IP_ALLOWLIST:0\.0\.0\.0\/0 ::\/0\}/,
    );
    expect(CADDYFILE).toMatch(/respond @admin_denied 403/);
  });
});
