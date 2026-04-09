import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import type { DownloadTransferFull } from "@/features/api/types";
import { getFileDownloadUrl, getDownloadAllUrl } from "../api/useDownload";
import { formatFileSize } from "@/features/utils/string-helper";

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
  password?: string;
}

export function DownloadView({ transfer, token, password }: DownloadViewProps) {
  const { t } = useTranslation();

  const expiresAt = new Date(transfer.expires_at).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <div className="download-view">
      <div className="download-view__header">
        <h1>{transfer.title || t("Transfer")}</h1>
        <p className="download-view__sender">
          {t("From {{name}}", { name: transfer.owner_name || transfer.owner_email })}
        </p>
        <p className="download-view__expires">{t("Expires on {{date}}", { date: expiresAt })}</p>
      </div>

      {transfer.message && (
        <p className="download-view__message">{transfer.message}</p>
      )}

      <div className="download-view__files">
        <h2>{t("Files ({{count}})", { count: transfer.files.length })}</h2>
        <ul>
          {transfer.files.map((file) => (
            <li key={file.id} className="download-view__file">
              <div>
                <span className="download-view__filename">{file.filename}</span>
                <span className="download-view__size">
                  {formatFileSize(file.size)}
                </span>
              </div>
              <a href={getFileDownloadUrl(token, file.id, password)}>
                <Button size="small" color="neutral">
                  {t("Download")}
                </Button>
              </a>
            </li>
          ))}
        </ul>
      </div>

      {transfer.files.length > 1 && (
        <div className="download-view__download-all">
          <a href={getDownloadAllUrl(token, password)}>
            <Button>{t("Download all (.zip)")}</Button>
          </a>
        </div>
      )}
    </div>
  );
}
