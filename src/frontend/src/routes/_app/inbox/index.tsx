import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/features/auth";
import { DepositList } from "@/features/deposits/components/DepositList";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";

// Files sent straight to the agent's address by people without an account.
const InboxRoute = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  if (!user) return <HomeLanding />;
  return (
    <div className="app-content deposits">
      <h1 className="deposits__title">{t("Inbox")}</h1>
      <p className="deposits__intro">
        {t(
          "Files that people without an account sent you through the send form.",
        )}
      </p>
      <DepositList />
    </div>
  );
};

export const Route = createFileRoute("/_app/inbox/")({
  component: InboxRoute,
});
