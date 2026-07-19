import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/features/auth";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";

const HomePage = () => {
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

export const Route = createFileRoute("/_app/")({
  component: HomePage,
});
