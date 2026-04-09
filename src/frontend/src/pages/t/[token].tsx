import { useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  useDownloadTransfer,
  useVerifyPassword,
} from "@/features/transfers/api/useDownload";
import { DownloadView } from "@/features/transfers/components/DownloadView";
import { PasswordForm } from "@/features/transfers/components/PasswordForm";
import type { DownloadTransferFull } from "@/features/api/types";

export default function DownloadPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const token = router.query.token as string | undefined;
  const { data, isLoading, isError } = useDownloadTransfer(token);
  const verifyPassword = useVerifyPassword(token || "");
  const [unlockedData, setUnlockedData] = useState<DownloadTransferFull | null>(
    null,
  );
  const [password, setPassword] = useState<string | undefined>();

  if (isLoading) {
    return (
      <div className="download-page">
        <p>{t("Loading...")}</p>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="download-page">
        <h1>{t("Transferts")}</h1>
        <p>{t("Transfer not found, expired or revoked.")}</p>
      </div>
    );
  }

  // Password protected and not yet unlocked
  if (data.has_password && !unlockedData) {
    return (
      <div className="download-page">
        <h1>{data.title || t("Transfer")}</h1>
        <PasswordForm
          onSubmit={(pwd) => {
            setPassword(pwd);
            verifyPassword.mutate(pwd, {
              onSuccess: (fullData) => {
                setUnlockedData(fullData);
              },
            });
          }}
          isPending={verifyPassword.isPending}
          isError={verifyPassword.isError}
        />
      </div>
    );
  }

  const transferData = unlockedData || (data as DownloadTransferFull);

  return (
    <div className="download-page">
      <DownloadView
        transfer={transferData}
        token={token!}
        password={password}
      />
    </div>
  );
}
