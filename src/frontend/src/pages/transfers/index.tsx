import type { ReactElement } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferList } from "@/features/transfers/components/TransferList";
import type { NextPageWithLayout } from "../_app";

const TransfersPage: NextPageWithLayout = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  if (!user) {
    return <HomeLanding />;
  }

  return (
    <div className="app-content">
      <header className="transfers-page__header">
        <h1>{t("My transfers")}</h1>
        <Link href="/" className="transfers-page__new-link">
          <Button icon={<Icon name="add" />}>{t("New transfer")}</Button>
        </Link>
      </header>
      <TransferList />
    </div>
  );
};

TransfersPage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default TransfersPage;
