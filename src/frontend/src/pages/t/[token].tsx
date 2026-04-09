import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { useDownloadTransfer } from "@/features/transfers/api/useDownload";
import { DownloadView } from "@/features/transfers/components/DownloadView";

export default function DownloadPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const token = router.query.token as string | undefined;
  const { data, isLoading, isError } = useDownloadTransfer(token);

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

  return (
    <div className="download-page">
      <DownloadView transfer={data} token={token!} />
    </div>
  );
}
