import type { ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";
import { TransferList } from "@/features/transfers/components/TransferList";
import type { NextPageWithLayout } from "./_app";

const HomePage: NextPageWithLayout = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  if (!user) {
    return <HomeLanding />;
  }

  return (
    <div className="app-content home">
      <div className="home__grid">
        <section className="home__upload">
          <TransferForm />
        </section>
        <section className="home__recent">
          <h2 className="home__recent-title">{t("Recent transfers")}</h2>
          <TransferList />
        </section>
      </div>
    </div>
  );
};

HomePage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default HomePage;
