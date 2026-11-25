import { createFileRoute } from "@tanstack/react-router";
import { InboxClaim } from "@/features/deposits/components/InboxClaim";

const ClaimRoute = () => {
  const { token } = Route.useSearch();
  return (
    <div className="app-content app-content--loading">
      <InboxClaim token={token ?? ""} />
    </div>
  );
};

export const Route = createFileRoute("/_app/inbox/claim")({
  component: ClaimRoute,
  validateSearch: (search: Record<string, unknown>): { token?: string } =>
    typeof search.token === "string" && search.token
      ? { token: search.token }
      : {},
});
