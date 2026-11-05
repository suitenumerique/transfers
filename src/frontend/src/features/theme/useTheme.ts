import { useOptionalConfig } from "@/features/providers/config";
import type { ThemeCustomization } from "./types";

// Stable reference: the applier's effects depend on slices of this object, and
// a fresh ``{}`` on every render would re-run them forever.
const NEUTRAL: ThemeCustomization = {};

/**
 * The resolved theme. Never null — an instance that configures nothing gets an
 * empty object, and every consumer treats an absent key as "hide it", so the
 * default install shows nobody's branding.
 *
 * Uses ``useOptionalConfig`` because the applier mounts above the loading gate
 * and must render before /config/ has answered.
 */
export function useTheme(): ThemeCustomization {
  return useOptionalConfig()?.theme_customization ?? NEUTRAL;
}
