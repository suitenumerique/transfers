import { type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { login, useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { LandingPage } from "@/features/transfers/components/LandingPage";
import { TransferForm } from "@/features/transfers/components/TransferForm";
import { TransferList } from "@/features/transfers/components/TransferList";
import type { NextPageWithLayout } from "./_app";

function AuthenticatedHome() {
  const { t } = useTranslation();

  return (
    <div className="app-content">
      <section className="home-section">
        <h1>{t("New transfer")}</h1>
        <TransferForm />
      </section>
      <section className="home-section">
        <h2>{t("Recent transfers")}</h2>
        <TransferList />
      </section>
    </div>
  );
}

const HomePage: NextPageWithLayout = () => {
  const { user } = useAuth();

  if (!user) {
    return <LandingPage onLogin={login} />;
  }

  return <AuthenticatedHome />;
};

HomePage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default HomePage;
