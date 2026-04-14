import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import type { DownloadTransferFull } from "@/features/api/types";
import { downloadFileWithPassword } from "../api/useDownload";
import { formatFileSize } from "@/features/utils/string-helper";

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
  password?: string | null;
}

export function DownloadView({ transfer, token, password }: DownloadViewProps) {
  const { t } = useTranslation();
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const expiresAt = new Date(transfer.expires_at).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const file = transfer.files[0];

  const handleDownload = async () => {
    if (!file) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadFileWithPassword(token, file.id, file.filename, password);
    } catch {
      setDownloadError(t("Download failed."));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="download-view">
      <div className="download-view__header">
        <h1>{transfer.title || t("Transfer")}</h1>
        <p className="download-view__sender">
          {t("From {{name}}", {
            name:
              transfer.owner_name ||
              transfer.owner_email ||
              t("Unknown sender"),
          })}
        </p>
        <p className="download-view__expires">
          {t("Expires on {{date}}", { date: expiresAt })}
        </p>
      </div>

      {file && (
        <div className="download-view__files">
          <div className="download-view__file">
            <div>
              <span className="download-view__filename">{file.filename}</span>
              <span className="download-view__size">
                {formatFileSize(file.size)}
              </span>
            </div>
            <Button onClick={handleDownload} disabled={downloading}>
              {downloading ? t("Downloading...") : t("Download")}
            </Button>
          </div>
          {downloadError && (
            <p className="download-view__error">{downloadError}</p>
          )}
        </div>
      )}
    </div>
  );
}
