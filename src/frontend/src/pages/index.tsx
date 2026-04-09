import { type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import { login, useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { TransferList } from "@/features/transfers/components/TransferList";
import type { NextPageWithLayout } from "./_app";

const HomePage: NextPageWithLayout = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  if (!user) {
    return (
      <div className="login-page">
        <h1>{t("Transferts")}</h1>
        <p>{t("Sovereign file transfer service")}</p>
        <ProConnectButton onClick={login} />
      </div>
    );
  }

  return (
    <div>
      <h1>{t("My transfers")}</h1>
      <TransferList />
    </div>
  );
};

HomePage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default HomePage;
