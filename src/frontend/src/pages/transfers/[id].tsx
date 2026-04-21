import { type ReactElement } from "react";
import { useRouter } from "next/router";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { TransferDetail } from "@/features/transfers/components/TransferDetail";
import { useTransfer } from "@/features/transfers/api/useTransfer";
import type { NextPageWithLayout } from "../_app";

const TransferDetailPage: NextPageWithLayout = () => {
  const router = useRouter();
  const id = router.query.id as string | undefined;
  const { data: transfer, isLoading, isError } = useTransfer(id);

  if (isLoading) return <p className="app-content">Chargement...</p>;
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
