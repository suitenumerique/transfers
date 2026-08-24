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
