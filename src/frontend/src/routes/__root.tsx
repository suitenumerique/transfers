import { createRootRoute, Outlet } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools";
import { CunninghamProvider } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";

import { Auth } from "@/features/auth";
import { ConfigProvider } from "@/features/providers/config";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

const RootShell = () => {
  // CunninghamProvider re-reads `currentLocale` on every render, so wiring it
  // to i18n.language here keeps Cunningham components localized as the user
  // switches languages.
  const { i18n } = useTranslation();

  return (
    <QueryClientProvider client={queryClient}>
      <CunninghamProvider theme="anct-light" currentLocale={i18n.language}>
        <ConfigProvider>
          <Auth>
            <Outlet />
          </Auth>
        </ConfigProvider>
      </CunninghamProvider>
      <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
      <TanStackRouterDevtools position="bottom-right" />
    </QueryClientProvider>
  );
};

export const Route = createRootRoute({
  component: RootShell,
});
