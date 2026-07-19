import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { TransferSuccess } from "@/features/transfers/components/TransferSuccess";
import { useTransfer } from "@/features/transfers/api/useTransfer";

const TransferConfirmPage = () => {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const { data: transfer, isLoading, isError } = useTransfer(id);

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
