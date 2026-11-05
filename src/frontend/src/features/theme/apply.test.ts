import { afterEach, describe, expect, it } from "vitest";

import {
  applyColors,
  applyFavicon,
  applyFontFaces,
  applyFontFamily,
  themeTargets,
} from "./apply";

const BRAND = "--c--globals--colors--brand-500";

function faviconSlots() {
  document.head.innerHTML = `
    <link rel="icon" media="(prefers-color-scheme: light)" href="/light.svg" />
    <link rel="icon" media="(prefers-color-scheme: dark)" href="/dark.svg" />
  `;
  return [...document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]')];
}

afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.documentElement.className = "";
  document.body.innerHTML = "";
  document.head.innerHTML = "";
});

describe("themeTargets", () => {
  it("always includes the root element", () => {
    expect(themeTargets()).toEqual([document.documentElement]);
  });

  it("does not list the root twice when it carries the theme class", () => {
    document.documentElement.className = "cunningham-theme--anct-light";

    expect(themeTargets()).toEqual([document.documentElement]);
  });

  it("also targets a wrapper that carries the theme class", () => {
    // Guards against a provider version that scopes the theme to a subtree:
    // its class would otherwise beat the value inherited from :root.
    document.body.innerHTML = '<div class="cunningham-theme--dsfr-light"></div>';
    const wrapper = document.querySelector("div")!;

    expect(themeTargets()).toEqual([document.documentElement, wrapper]);
  });
});

describe("applyColors", () => {
  it("writes each key as the CSS property it names", () => {
    applyColors({ [BRAND]: "#C83F49" });

    expect(document.documentElement.style.getPropertyValue(BRAND)).toBe("#C83F49");
  });

  it("overrides the compiled token, which is the point", () => {
    // The stylesheet declares the token on :root; an inline style on the same
    // element wins, so a palette nobody compiled still applies.
    document.documentElement.className = "cunningham-theme--anct-light";
    applyColors({ [BRAND]: "#C83F49" });

    expect(document.documentElement.style.getPropertyValue(BRAND)).toBe("#C83F49");
  });

  it("reaches a themed wrapper too", () => {
    document.body.innerHTML = '<div class="cunningham-theme--dsfr-light"></div>';
    applyColors({ [BRAND]: "#C83F49" });

    expect(
      document.querySelector("div")!.style.getPropertyValue(BRAND),
    ).toBe("#C83F49");
  });

  it("removes what it set on cleanup", () => {
    const cleanup = applyColors({ [BRAND]: "#C83F49" });
    cleanup();

    expect(document.documentElement.style.getPropertyValue(BRAND)).toBe("");
  });

  it("does nothing when the theme carries no colours", () => {
    applyColors(undefined);

    expect(document.documentElement.getAttribute("style")).toBeNull();
  });
});

describe("applyFontFamily", () => {
  it("sets the base and accent families together", () => {
    applyFontFamily("Hanken Grotesk, sans-serif");

    const style = document.documentElement.style;
    expect(style.getPropertyValue("--c--globals--font--families--base")).toBe(
      "Hanken Grotesk, sans-serif",
    );
    expect(style.getPropertyValue("--c--globals--font--families--accent")).toBe(
      "Hanken Grotesk, sans-serif",
    );
  });

  it("reverts on cleanup", () => {
    applyFontFamily("Inter")();

    expect(
      document.documentElement.style.getPropertyValue(
        "--c--globals--font--families--base",
      ),
    ).toBe("");
  });
});

describe("applyFavicon", () => {
  it("matches each slot to its colour scheme", () => {
    const [light, dark] = faviconSlots();

    applyFavicon({
      light: { href: "/operator-light.png" },
      dark: { href: "/operator-dark.png" },
    });

    expect(light.getAttribute("href")).toBe("/operator-light.png");
    expect(dark.getAttribute("href")).toBe("/operator-dark.png");
  });

  it("uses the only favicon it was given for both slots", () => {
    const [light, dark] = faviconSlots();

    applyFavicon({ light: { href: "/only.png" } });

    expect(light.getAttribute("href")).toBe("/only.png");
    expect(dark.getAttribute("href")).toBe("/only.png");
  });

  it("restores the shipped favicons on cleanup", () => {
    const [light, dark] = faviconSlots();

    applyFavicon({ light: { href: "/a.png" }, dark: { href: "/b.png" } })();

    expect(light.getAttribute("href")).toBe("/light.svg");
    expect(dark.getAttribute("href")).toBe("/dark.svg");
  });

  it("leaves the slots alone when the theme carries no favicon", () => {
    const [light] = faviconSlots();

    applyFavicon(undefined);
    applyFavicon({ light: {} });

    expect(light.getAttribute("href")).toBe("/light.svg");
  });
});

describe("applyFontFaces", () => {
  const sheet = () => document.querySelector("style[data-theme-font-faces]");
  const rules = () => sheet()?.textContent ?? "";

  it("declares nothing when the theme carries no face", () => {
    applyFontFaces(undefined);
    applyFontFaces([]);

    expect(sheet()).toBeNull();
  });

  it("writes a rule a browser can use", () => {
    applyFontFaces([
      {
        family: "Marianne",
        src: "https://assets.example.org/marianne.woff2",
        weight: "100 900",
        unicodeRange: "U+0000-00FF, U+0131",
      },
    ]);

    expect(rules()).toContain('font-family: "Marianne"');
    expect(rules()).toContain(
      'src: url("https://assets.example.org/marianne.woff2") format("woff2")',
    );
    expect(rules()).toContain("font-weight: 100 900");
    expect(rules()).toContain("unicode-range: U+0000-00FF, U+0131");
  });

  it("defaults font-display to swap, so text is never invisible", () => {
    applyFontFaces([{ family: "A", src: "/a.woff2" }]);

    expect(rules()).toContain("font-display: swap");
  });

  it("removes its stylesheet on cleanup", () => {
    const cleanup = applyFontFaces([{ family: "A", src: "/a.woff2" }]);
    expect(sheet()).not.toBeNull();

    cleanup();

    expect(sheet()).toBeNull();
  });

  it("skips a face that names nothing or loads nothing", () => {
    applyFontFaces([
      { family: "", src: "/a.woff2" },
      { family: "A", src: "" },
    ]);

    expect(sheet()).toBeNull();
  });

  it("escapes a quote rather than letting it close the rule", () => {
    applyFontFaces([
      { family: 'A"; } body { display: none; } @media all {', src: "/a.woff2" },
    ]);

    // The payload survives as text inside the quoted family name, which is
    // exactly where it is harmless: the sheet still holds one rule, not three.
    const style = sheet() as HTMLStyleElement;
    expect(style.sheet?.cssRules).toHaveLength(1);
    expect(rules()).toContain('\\"');
  });

  it("drops a descriptor that is not a descriptor", () => {
    applyFontFaces([
      { family: "A", src: "/a.woff2", weight: "400; } body { display: none" },
    ]);

    expect(rules()).not.toContain("display: none");
    expect(rules()).not.toContain("font-weight");
  });

  it("drops a unicode-range that is not one", () => {
    applyFontFaces([
      { family: "A", src: "/a.woff2", unicodeRange: "} body { display: none" },
    ]);

    expect(rules()).not.toContain("display: none");
    expect(rules()).not.toContain("unicode-range");
  });
});
