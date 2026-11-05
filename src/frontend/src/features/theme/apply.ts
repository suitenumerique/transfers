import type { ThemeCustomization, ThemeFontFace } from "./types";

const FONT_PROPERTIES = [
  "--c--globals--font--families--base",
  "--c--globals--font--families--accent",
];

const THEME_CLASS_SELECTOR = '[class*="cunningham-theme--"]';

/** Undoes what an apply* call did. */
export type Cleanup = () => void;

const NOOP: Cleanup = () => {};

/**
 * Where to write the custom properties.
 *
 * Cunningham's tokens are CSS custom properties, so an inline style overrides
 * them without regenerating anything — that is the whole trick behind "one
 * image, N operators". The provider shipped in ``ui-kit`` adds its
 * ``cunningham-theme--*`` class to ``:root``, i.e. the very element an inline
 * style lands on, so writing to ``documentElement`` is enough and wins on
 * specificity. We import the provider from ``cunningham-react`` though, and
 * should a version of it ever wrap its children in a div instead, that div's
 * class would beat an inherited value for its whole subtree. Writing to both
 * costs nothing and makes the result independent of which one we got — and of
 * effect ordering, since a parent's effect runs after its children's.
 */
export function themeTargets(): HTMLElement[] {
  const targets = new Set<HTMLElement>([document.documentElement]);
  document
    .querySelectorAll<HTMLElement>(THEME_CLASS_SELECTOR)
    .forEach((element) => targets.add(element));
  return [...targets];
}

function setProperties(names: string[], value: (name: string) => string): Cleanup {
  const targets = themeTargets();
  targets.forEach((target) => {
    names.forEach((name) => target.style.setProperty(name, value(name)));
  });

  return () => {
    targets.forEach((target) => {
      names.forEach((name) => target.style.removeProperty(name));
    });
  };
}

/** Applies ``theme.colors``, whose keys are already CSS property names. */
export function applyColors(colors: Record<string, string> | undefined): Cleanup {
  if (!colors) {
    return NOOP;
  }

  return setProperties(Object.keys(colors), (name) => colors[name]);
}

/**
 * Applies ``theme.fontFamily`` to the base and accent families.
 *
 * Sets the declaration only — no font file is fetched, so a face that isn't
 * already self-hosted remains the operator's business.
 */
export function applyFontFamily(fontFamily: string | undefined): Cleanup {
  if (!fontFamily) {
    return NOOP;
  }

  return setProperties(FONT_PROPERTIES, () => fontFamily);
}

/**
 * Points the declared ``<link rel="icon">`` slots at the theme's favicons,
 * matching a slot to a scheme by its ``media`` attribute.
 *
 * A deployment that sets only one of the two gets it in both slots, rather
 * than a mismatched pair.
 */
export function applyFavicon(favicon: ThemeCustomization["favicon"]): Cleanup {
  const light = favicon?.light?.href;
  const dark = favicon?.dark?.href;
  if (!light && !dark) {
    return NOOP;
  }

  const previous = new Map<HTMLLinkElement, string>();
  document
    .querySelectorAll<HTMLLinkElement>('link[rel="icon"]')
    .forEach((link) => {
      const href = (link.media.includes("dark") ? dark : light) ?? light ?? dark;
      if (!href) {
        return;
      }

      previous.set(link, link.getAttribute("href") ?? "");
      link.setAttribute("href", href);
    });

  return () => {
    previous.forEach((href, link) => link.setAttribute("href", href));
  };
}

// A descriptor is written into the rule unquoted, so only a conservative shape
// goes through; anything else is dropped rather than escaped. The deployment's
// configuration is trusted, but a stray quote should cost one descriptor, not
// the whole stylesheet.
const SAFE_DESCRIPTOR = /^[\w\s,+.%-]+$/;
const SAFE_UNICODE_RANGE =
  /^[Uu]\+[0-9A-Fa-f?]{1,6}(-[0-9A-Fa-f]{1,6})?(\s*,\s*[Uu]\+[0-9A-Fa-f?]{1,6}(-[0-9A-Fa-f]{1,6})?)*$/;

/** Quote as a CSS string, so an operator's text cannot close the rule. */
function cssString(value: string): string {
  return `"${value.replace(/[\\"]/g, (char) => `\\${char}`)}"`;
}

function fontFaceRule(face: ThemeFontFace): string | null {
  const family = face.family?.trim();
  const source = face.src?.trim();
  // A face missing either names nothing or loads nothing. Control characters
  // in a URL are rejected outright: no legitimate one carries them.
  if (!family || !source || /[\u0000-\u001f]/.test(source)) {
    return null;
  }

  const display =
    face.display && SAFE_DESCRIPTOR.test(face.display) ? face.display : "swap";
  const lines = [
    `  font-family: ${cssString(family)};`,
    `  src: url(${cssString(source)}) format("woff2");`,
    `  font-display: ${display};`,
  ];
  if (face.weight && SAFE_DESCRIPTOR.test(face.weight)) {
    lines.push(`  font-weight: ${face.weight};`);
  }
  if (face.style && SAFE_DESCRIPTOR.test(face.style)) {
    lines.push(`  font-style: ${face.style};`);
  }
  if (face.unicodeRange && SAFE_UNICODE_RANGE.test(face.unicodeRange)) {
    lines.push(`  unicode-range: ${face.unicodeRange};`);
  }

  return `@font-face {\n${lines.join("\n")}\n}`;
}

/**
 * Declares the deployment's font files, as ``@font-face`` rules.
 *
 * ``fontFamily`` only *names* a family: without this an operator could name
 * one the browser has no way to load, and the stack would fall through to the
 * system font. The rules go in a ``<style>`` of our own, so the cleanup is a
 * single removal and nothing we add can disturb the app's own stylesheet.
 *
 * ``woff2`` only. Every browser still in service supports it, and the second
 * format a font bundle usually drags along is pure weight.
 */
export function applyFontFaces(faces: ThemeCustomization["fontFaces"]): Cleanup {
  const rules = (faces ?? [])
    .map(fontFaceRule)
    .filter((rule): rule is string => rule !== null);
  if (rules.length === 0) {
    return NOOP;
  }

  const style = document.createElement("style");
  style.setAttribute("data-theme-font-faces", "");
  style.textContent = rules.join("\n\n");
  document.head.appendChild(style);

  return () => style.remove();
}
