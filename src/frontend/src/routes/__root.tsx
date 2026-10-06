import { createRootRoute, Outlet } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools";
import { CunninghamProvider } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";

import { Auth } from "@/features/auth";
import {
  ConfigProvider,
  useOptionalConfig,
} from "@/features/providers/config";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

// Cunningham sits inside ConfigProvider so the theme comes from /config/
// instead of being compiled in. ``FRONTEND_THEME`` empty — or not answered
// yet — means the neutral "default" theme, never an operator's branding.
const ThemedShell = () => {
  // CunninghamProvider re-reads `currentLocale` on every render, so wiring it
  // to i18n.language here keeps Cunningham components localized as the user
  // switches languages.
  const { i18n } = useTranslation();
  const config = useOptionalConfig();

  return (
    <CunninghamProvider
      theme={config?.FRONTEND_THEME || "default"}
      currentLocale={i18n.language}
    >
      <Auth>
        <Outlet />
      </Auth>
    </CunninghamProvider>
  );
};

const RootShell = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <ThemedShell />
      </ConfigProvider>
      <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
      <TanStackRouterDevtools position="bottom-right" />
    </QueryClientProvider>
  );
};

export const Route = createRootRoute({
  component: RootShell,
});
