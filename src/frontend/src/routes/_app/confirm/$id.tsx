import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { TransferSuccess } from "@/features/transfers/components/TransferSuccess";
import { useTransfer } from "@/features/transfers/api/useTransfer";

const TransferConfirmPage = () => {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const { data: transfer, isLoading, isError } = useTransfer(id);

  // The form passes the encryption key fragment via the navigation hash for
  // link-mode finalizes. We snapshot it once at initial render and strip
  // it from the visible URL on mount, so keys never end up in the
  // address bar beyond the moment of arrival, and a refresh of
  // /confirm/<id> loses the fragment (matches the "we don't store the
  // key" promise).
  const [encryptionFragment] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.location.hash.replace(/^#/, "") || null;
  });
  useEffect(() => {
    if (!encryptionFragment) return;
    try {
      // Strip the fragment but keep the query string (analytics utm=…,
      // debug flags, or router state can all ride on ``search``).
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    } catch {
      // replaceState can throw in exotic sandboxes; the URL stays as-is
      // but the component already has the fragment in state.
    }
  }, [encryptionFragment]);

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
            encryptionFragment={encryptionFragment}
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
