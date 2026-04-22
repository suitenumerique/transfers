import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import type { DownloadTransferFull } from "@/features/api/types";
import { downloadFile } from "../api/useDownload";
import { formatFileSize } from "@/features/utils/string-helper";

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
}

export function DownloadView({ transfer, token }: DownloadViewProps) {
  const { t } = useTranslation();

  const expiresAt = new Date(transfer.expires_at).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const totalSize = transfer.files.reduce((a, f) => a + f.size, 0);

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

      {transfer.files.length > 0 && (
        <div className="download-view__files">
          <h2 className="download-view__files-title">
            {t("{{count}} file", { count: transfer.files.length })}{" "}
            <span className="download-view__files-total">
              ({formatFileSize(totalSize)})
            </span>
          </h2>
          <ul className="download-view__file-list">
            {transfer.files.map((file) => (
              <li key={file.id} className="download-view__file">
                <div className="download-view__file-meta">
                  <span className="download-view__filename">
                    {file.filename}
                  </span>
                  <span className="download-view__size">
                    {formatFileSize(file.size)}
                  </span>
                </div>
                <Button onClick={() => downloadFile(token, file.id)}>
                  {t("Download")}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
