import { type ReactElement } from "react";
import { useRouter } from "next/router";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { TransferDetail } from "@/features/transfers/components/TransferDetail";
import { useTransfer } from "@/features/transfers/api/useTransfer";
import type { NextPageWithLayout } from "../_app";

const TransferDetailPage: NextPageWithLayout = () => {
  const router = useRouter();
  const id = router.query.id as string | undefined;
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
    <div className="app-content">
      <TransferDetail transfer={transfer} />
    </div>
  );
};

TransferDetailPage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default TransferDetailPage;
