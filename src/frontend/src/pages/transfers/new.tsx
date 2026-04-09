import { type ReactElement } from "react";
import Link from "next/link";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { TransferForm } from "@/features/transfers/components/TransferForm";
import type { NextPageWithLayout } from "../_app";

const NewTransferPage: NextPageWithLayout = () => {
  return (
    <div>
      <Link href="/">&larr; Retour</Link>
      <h1>Nouveau transfert</h1>
      <TransferForm />
    </div>
  );
};

NewTransferPage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default NewTransferPage;
