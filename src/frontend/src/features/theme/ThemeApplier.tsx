import { useEffect } from "react";

import {
  applyColors,
  applyFavicon,
  applyFontFaces,
  applyFontFamily,
} from "./apply";
import { useTheme } from "./useTheme";

/**
 * Applies the runtime half of the theme: colours, fonts and favicon.
 * Renders nothing.
 *
 * Mounted above the loading gate, so it runs with an empty theme until
 * /config/ answers and then applies whatever came back. Each effect reverts
 * itself on cleanup, so a configuration that changes under us never leaves a
 * half-applied palette behind.
 */
export function ThemeApplier() {
  const { colors, fontFamily, fontFaces, favicon } = useTheme();

  useEffect(() => applyColors(colors), [colors]);
  // Faces before family: declaring the file first means the family it
  // names resolves on the very first paint that uses it.
  useEffect(() => applyFontFaces(fontFaces), [fontFaces]);
  useEffect(() => applyFontFamily(fontFamily), [fontFamily]);
  useEffect(() => applyFavicon(favicon), [favicon]);

  return null;
}
