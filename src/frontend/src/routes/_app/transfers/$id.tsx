import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { TransferDetail } from "@/features/transfers/components/TransferDetail";
import { useTransfer } from "@/features/transfers/api/useTransfer";

const TransferDetailPage = () => {
  const { t } = useTranslation();
  const { id } = Route.useParams();
  const { data: transfer, isLoading, isError } = useTransfer(id);

  if (isLoading)
    return (
      <div className="app-content app-content--loading">
        <Spinner size="lg" />
      </div>
    );
  if (isError || !transfer)
    return <p className="app-content">{t("Transfer not found.")}</p>;

  return (
    <div className="app-content">
      <TransferDetail transfer={transfer} />
    </div>
  );
};

export const Route = createFileRoute("/_app/transfers/$id")({
  component: TransferDetailPage,
});
