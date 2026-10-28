import { useEffect } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { useAuth } from "@/features/auth";
import { takePendingClaim } from "@/features/deposits/api/claimInbound";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";

const HomePage = () => {
  const { user } = useAuth();
  const navigate = useNavigate();

  // Back from the sign-in a claim link started: resume the claim.
  useEffect(() => {
    if (!user) return;
    const token = takePendingClaim();
    if (token) void navigate({ to: "/inbox/claim", search: { token }, replace: true });
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
