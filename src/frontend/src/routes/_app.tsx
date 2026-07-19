import { createFileRoute, Outlet } from "@tanstack/react-router";

import { MainLayout } from "@/features/layouts/components/main/MainLayout";

// Pathless layout route: wraps every "app" page (home, transfers, confirm…)
// in the shared MainLayout so the shell (sidebar + top bar) stays mounted
// across navigations — the TanStack equivalent of the old Next.js
// `getLayout` pattern. The download page (`/t/$token`) lives outside this
// group and keeps its own standalone chrome.
const AppLayoutRoute = () => (
  <MainLayout>
    <Outlet />
  </MainLayout>
);

export const Route = createFileRoute("/_app")({
  component: AppLayoutRoute,
});
