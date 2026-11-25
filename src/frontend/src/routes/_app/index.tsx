import { useEffect } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { takeReturnPath, useAuth } from "@/features/auth";
import { takePendingClaim } from "@/features/deposits/api/claimInbound";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";

const HomePage = () => {
  const { user } = useAuth();
  const navigate = useNavigate();

  // Back from a sign-in another page started: resume a claim, or go back
  // to that page (in full, so a deposit link keeps its key fragment).
  useEffect(() => {
    if (!user) return;
    const token = takePendingClaim();
    const path = takeReturnPath();
    if (token) {
      void navigate({ to: "/inbox/claim", search: { token }, replace: true });
    } else if (path && path !== "/") {
      window.location.replace(path);
    }
  }, [user, navigate]);

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
