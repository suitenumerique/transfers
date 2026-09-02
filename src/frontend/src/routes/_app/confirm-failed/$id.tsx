import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { TransferFailed } from "@/features/transfers/components/TransferFailed";
import { useTransfer } from "@/features/transfers/api/useTransfer";

const TransferConfirmFailedPage = () => {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const { data: transfer, isLoading, isError } = useTransfer(id);

  // Same contract as /confirm/$id: TransferForm forwards the confidential
  // key fragment via the navigation hash for email-mode finalizes too —
  // whether every invitation went out or not. This page used to drop it
  // on the floor, so a confidential transfer whose emails partially
  // failed landed the sender on a screen that never showed the key, then
  // sent them to /transfers/<id> which by design can't reconstruct it.
  // Snapshot once, strip from the visible URL on mount (matches the "we
  // don't store the key" promise: a refresh loses it).
  const [encryptionFragment] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.location.hash.replace(/^#/, "") || null;
  });
  useEffect(() => {
    if (!encryptionFragment) return;
    try {
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
          <TransferFailed
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

export const Route = createFileRoute("/_app/confirm-failed/$id")({
  component: TransferConfirmFailedPage,
});
