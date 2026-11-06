import { useOptionalConfig } from "@/features/providers/config";
import { useTheme } from "./useTheme";

/**
 * The operator links, read from the theme and falling back to the flat config
 * keys that preceded it.
 *
 * ``HELP_URL``, ``SUPPORT_URL`` and ``LAGAUFRE`` shipped before the theme
 * existed. They stay honoured for a version so a deployment migrates on its
 * own schedule; keeping the fallbacks here rather than in each consumer means
 * there is exactly one place to delete when they go.
 */

export function useHelpUrl(): string {
  const theme = useTheme();
  const config = useOptionalConfig();
  return theme.help?.documentation_url || config?.HELP_URL || "";
}

export function useSupportUrl(): string {
  const theme = useTheme();
  const config = useOptionalConfig();

  if (theme.help?.support_url) {
    return theme.help.support_url;
  }

  // ``docs`` only models a mailto. Accept it so a file written for docs works,
  // and turn it into something an <a href> can use.
  if (theme.help?.support_mailto) {
    return `mailto:${theme.help.support_mailto}`;
  }

  return config?.SUPPORT_URL || "";
}

export type WaffleConfig = { widgetPath: string; apiUrl: string };

/**
 * The app switcher's two URLs, or null. Opt-in both ways: nothing renders
 * until a deployment supplies both, since the widget pulls a third-party
 * script and lists another operator's services.
 */
export function useWaffle(): WaffleConfig | null {
  const theme = useTheme();
  const config = useOptionalConfig();

  const widgetPath = theme.waffle?.widgetPath ?? config?.LAGAUFRE?.widget_url;
  const apiUrl = theme.waffle?.apiUrl ?? config?.LAGAUFRE?.api_url;

  if (!widgetPath || !apiUrl) {
    return null;
  }

  return { widgetPath, apiUrl };
}
