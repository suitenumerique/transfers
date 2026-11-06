/**
 * The theme object served by /config/ under ``theme_customization``.
 *
 * Shaped as a superset of the theme customization JSON of ``docs`` and
 * ``drive``: every key below that those two already define carries the same
 * name and the same meaning, so a file written for one of them works here
 * unchanged. ``colors``, ``fontFamily``, ``help.support_url`` and
 * ``home.learn_more_url`` are the additions — see the spec.
 *
 * Deliberately open (``[key: string]: unknown``): the goal is one shared file
 * across the Suite's products, so this app must carry keys meant for another
 * one without complaining about them.
 */

export interface ThemeImage {
  src: string;
  alt?: string;
  width?: number | string;
  height?: number | string;
  style?: Record<string, string | number>;
  withTitle?: boolean;
}

/** One ``@font-face`` rule, as a deployment declares it. */
export interface ThemeFontFace {
  /** Must match what ``fontFamily`` names, or nothing uses the file. */
  family: string;
  /** URL of the font file. Same-origin, a ``data:`` URI, or an origin the
   * frontend's ``font-src`` allows (TRANSFERS_FRONTEND_THEME_ASSET_ORIGIN):
   * fonts are subject to the cross-origin rules *and* to the CSP, so being
   * CORS-enabled is not enough on its own. */
  src: string;
  /** ``400``, or a range such as ``100 900`` for a variable font. */
  weight?: string;
  style?: string;
  /** Defaults to ``swap``: show the fallback at once, swap when the file
   * lands. Never leave the page's text invisible waiting on a font. */
  display?: string;
  /** Limits the file to the characters it carries, so the browser fetches it
   * only when the page needs them. */
  unicodeRange?: string;
}

/** Spread onto a ``<link rel="icon">``; ``href`` is the only part we read. */
export interface ThemeFaviconLink {
  href?: string;
  type?: string;
  [key: string]: unknown;
}

export interface ThemeLegalLinks {
  personal_data?: string;
  terms_of_use?: string;
  accessibility_statement?: string;
  legal_notice?: string;
}

/**
 * ``LaGaufreV2Props``, narrowed to what we pass. Declared locally rather than
 * imported from the kit: the two keys below are the whole contract between the
 * theme and the widget, and a type import would pin this file to one kit
 * version while four are in use across the Suite.
 */
export interface ThemeWaffle {
  widgetPath?: string;
  apiUrl?: string;
  [key: string]: unknown;
}

export interface ThemeCustomization {
  /**
   * Cunningham custom properties, by their exact CSS names — e.g.
   * ``{"--c--globals--colors--brand-500": "#C83F49"}``. Applied at runtime
   * over whichever compiled theme ``FRONTEND_THEME`` selected, which is what
   * lets one image serve operators whose palette nobody compiled.
   */
  colors?: Record<string, string>;
  /**
   * Base and accent font family. Sets the CSS declaration only — it serves no
   * font file, so a self-hosted face remains the operator's business.
   */
  fontFamily?: string;
  /**
   * Font files the deployment serves, turned into ``@font-face`` rules at
   * runtime. ``fontFamily`` only names a family; without this an operator can
   * name one the browser has no way to load. Not part of the ``docs`` theme
   * today -- an addition, proposed with the rest of the superset.
   */
  fontFaces?: ThemeFontFace[];
  favicon?: {
    light?: ThemeFaviconLink;
    dark?: ThemeFaviconLink;
  };
  header?: {
    logo?: ThemeImage;
    icon?: ThemeImage;
  };
  home?: {
    /** Swaps the neutral "Sign in" button for the ProConnect one. */
    "with-proconnect"?: boolean;
    "icon-banner"?: ThemeImage;
    /** "Learn more" on the public landing. Empty hides the button. */
    learn_more_url?: string;
  };
  help?: {
    documentation_url?: string;
    /** ``docs`` only has ``support_mailto``; ours may be any URL. */
    support_url?: string;
    support_mailto?: string;
    legal_links?: ThemeLegalLinks;
  };
  waffle?: ThemeWaffle;
  [key: string]: unknown;
}
