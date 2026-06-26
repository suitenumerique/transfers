import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { TransferSuccess } from "@/features/transfers/components/TransferSuccess";
import { useTransfer } from "@/features/transfers/api/useTransfer";

const TransferConfirmPage = () => {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const { data: transfer, isLoading, isError } = useTransfer(id);

  // The form passes the E2E key fragment via the navigation hash for
  // link-mode finalizes. We snapshot it once at initial render and strip
  // it from the visible URL on mount, so keys never end up in the
  // address bar beyond the moment of arrival, and a refresh of
  // /confirm/<id> loses the fragment (matches the "we don't store the
  // key" promise).
  const [e2eFragment] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.location.hash.replace(/^#/, "") || null;
  });
  useEffect(() => {
    if (!e2eFragment) return;
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch {
      // replaceState can throw in exotic sandboxes; the URL stays as-is
      // but the component already has the fragment in state.
    }
  }, [e2eFragment]);

  if (isLoading)
    return (
      <div className="app-content app-content--loading">
        <Spinner size="lg" />
      </div>
    );
  if (isError || !transfer)
    return <p className="app-content">Transfert introuvable.</p>;

  return (
    <div className="app-content home">
      <div className="home__grid">
        <section className="home__upload">
          <TransferSuccess
            transfer={transfer}
            e2eFragment={e2eFragment}
            onNewTransfer={() => navigate({ to: "/" })}
            onGoToDetail={() =>
              navigate({ to: "/transfers/$id", params: { id: transfer.id } })
            }
          />
        </section>
      </div>
    </div>
  );
};

export const Route = createFileRoute("/_app/confirm/$id")({
  component: TransferConfirmPage,
});
