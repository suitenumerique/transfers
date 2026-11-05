import { afterEach, describe, expect, it, vi } from "vitest";

import { login } from "./index";

/**
 * Replace window.location with a stub. jsdom's own location cannot be
 * navigated, and ``replace`` is what we want to inspect anyway.
 */
function stubLocation(href: string) {
  const replace = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { href, origin: new URL(href).origin, replace },
  });
  return replace;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("login", () => {
  it("carries the page it was called from, so a second domain comes back to itself", () => {
    vi.stubEnv("NEXT_PUBLIC_API_ORIGIN", "http://opsn1.localhost:9981");
    const replace = stubLocation("http://opsn1.localhost:9990/transfers/42");

    login();

    expect(replace).toHaveBeenCalledWith(
      "http://opsn1.localhost:9981/api/v1.0/authenticate/" +
        "?next=http%3A%2F%2Fopsn1.localhost%3A9990%2Ftransfers%2F42",
    );
  });

  it("leaves the fragment behind, where a confidential key lives", () => {
    vi.stubEnv("NEXT_PUBLIC_API_ORIGIN", "");
    const replace = stubLocation("http://example.test/t/abc123#Zm9vYmFyLWtleQ");

    login();

    const next = new URL(replace.mock.calls[0][0]).searchParams.get("next");
    expect(next).toBe("http://example.test/t/abc123");
    expect(replace.mock.calls[0][0]).not.toContain("Zm9vYmFyLWtleQ");
  });

  it("falls back to the page's own origin when no API origin is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_API_ORIGIN", "");
    const replace = stubLocation("http://example.test/");

    login();

    expect(replace).toHaveBeenCalledWith(
      "http://example.test/api/v1.0/authenticate/?next=http%3A%2F%2Fexample.test%2F",
    );
  });
});
