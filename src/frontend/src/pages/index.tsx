import type { ReactElement } from "react";
import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";

import type { NextPageWithLayout } from "./_app";

const HomePage: NextPageWithLayout = () => {
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
      </div>
    </div>
  );
};

HomePage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default HomePage;
