import { type ReactElement } from "react";
import { useRouter } from "next/router";
import Link from "next/link";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { TransferDetail } from "@/features/transfers/components/TransferDetail";
import { TransferTimeline } from "@/features/transfers/components/TransferTimeline";
import { useTransfer } from "@/features/transfers/api/useTransfer";
import type { NextPageWithLayout } from "../_app";

const TransferDetailPage: NextPageWithLayout = () => {
  const router = useRouter();
  const id = router.query.id as string | undefined;
  const { data: transfer, isLoading, isError } = useTransfer(id);

  if (isLoading) return <p>Chargement...</p>;
  if (isError || !transfer) return <p>Transfert introuvable.</p>;

  return (
    <div className="app-content">
      <Link href="/">&larr; Retour</Link>
      <TransferDetail transfer={transfer} />
      <TransferTimeline transferId={transfer.id} />
    </div>
  );
};

TransferDetailPage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default TransferDetailPage;
