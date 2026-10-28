import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Tooltip,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import {
  CheckmarkShield,
  Doc,
  FileError,
  Retry,
  Trash,
  Warning,
  WarningFilled,
} from "@gouvfr-lasuite/ui-kit/icons";
import type { DepositReceipt } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import {
  fileKey,
  SubmitCancelledError,
  useTransferDraft,
} from "@/features/transfers/api/useTransferDraft";
import { FileDropZone } from "@/features/transfers/components/FileDropZone";
import { FileItem } from "@/features/transfers/components/FileItem";
import {
  ImportSpinner,
  percent,
  UploadRing,
} from "@/features/transfers/components/TransferForm";
import { isScanBlocking } from "@/features/transfers/utils/scanStatus";
import { formatFileSize } from "@/features/utils/string-helper";
import { depositErrorMessage } from "./depositErrors";

interface DepositUploadProps {
  // The session token a verified code opened.
  sessionToken: string;
  title: string;
  maxDepositSize: number;
  maxFiles: number;
  onSent: (receipt: DepositReceipt) => void;
}

// The upload step of a deposit: the same encrypted multipart upload as the
// agent's form, against the depositor's own draft endpoints.
export function DepositUpload({
  sessionToken,
  title,
  maxDepositSize,
  maxFiles,
  onSent,
}: DepositUploadProps) {
  const { t } = useTranslation();
  const config = useConfig();
  const draft = useTransferDraft({
    basePath: "/deposit-drafts",
    headers: { "X-Deposit-Token": sessionToken },
  });
  const [fileError, setFileError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const sentRef = useRef(false);
  const maxFileSize = Math.min(config.TRANSFER_MAX_FILE_SIZE, maxDepositSize);

  // Leaving before sending drops what was uploaded.
  useEffect(() => {
    return () => {
      if (!sentRef.current) void draft.abort();
    };
  }, []);

  const handleFiles = (incoming: File[]) => {
    setFileError(null);
    setSubmitError(null);
    const oversized = incoming.find((f) => f.size > maxFileSize);
    if (oversized) {
      setFileError(
        t("File too large: {{name}} ({{size}}). Maximum: {{max}}.", {
          name: oversized.name,
          size: formatFileSize(oversized.size),
          max: formatFileSize(maxFileSize),
        }),
      );
      return;
    }
    const existing = new Set(draft.files.map((f) => f.key));
    const newFiles = incoming.filter((f) => !existing.has(fileKey(f)));
    if (draft.files.length + newFiles.length > maxFiles) {
      setFileError(t("Too many files. Maximum: {{max}}.", { max: maxFiles }));
      return;
    }
    const total =
      draft.files.reduce((sum, f) => sum + f.total, 0) +
      newFiles.reduce((sum, f) => sum + f.size, 0);
    if (total > maxDepositSize) {
      setFileError(
        t("Total size exceeds the limit of {{max}}.", {
          max: formatFileSize(maxDepositSize),
        }),
      );
      return;
    }
    newFiles.forEach((f) => draft.addFile(f));
  };

  const busy = draft.isAwaitingUploads || draft.isFinalizing;
  const hasFiles = draft.files.length > 0;
  const anyError = draft.files.some((f) => f.state === "error");
  // Infected, scan error or scan timed out: sending again would be refused.
  const scanBlocking = isScanBlocking(
    draft.files,
    (f) => f.scanStatus,
    draft.scanTimedOut,
  );

  const send = async () => {
    if (busy || !hasFiles || anyError || scanBlocking) return;
    setSubmitError(null);
    try {
      const receipt = (await draft.submit({
        title,
      })) as unknown as DepositReceipt;
      sentRef.current = true;
      onSent(receipt);
    } catch (err) {
      if (err instanceof SubmitCancelledError) return;
      setSubmitError(depositErrorMessage(err));
    }
  };

  return (
    <div className="deposit-upload">
      <FileDropZone
        onChange={handleFiles}
        errorMessage={fileError}
        maxTotalSize={maxDepositSize}
      />

      {hasFiles && (
        <ul
          className="deposit-upload__file-list"
          aria-label={t("Selected files")}
        >
          {draft.files.map((df) => {
            const pct = percent(df);
            const isUploading = df.state === "uploading";
            const isDone = df.state === "done";
            const icon = isUploading ? (
              <UploadRing percent={pct} />
            ) : df.state === "registering" ? (
              <ImportSpinner />
            ) : df.state === "error" ? (
              <FileError />
            ) : (
              <Doc />
            );
            return (
              <FileItem
                key={df.key}
                icon={icon}
                name={df.name}
                size={formatFileSize(df.total)}
                state={
                  df.state === "error" ||
                  df.scanStatus === "infected" ||
                  (df.scanStatus === "error" && df.scanErrorKind === "file")
                    ? "error"
                    : isDone
                      ? "done"
                      : "default"
                }
                extras={
                  <>
                    {isUploading && (
                      <span
                        className="file-item__pct"
                        role="progressbar"
                        aria-valuenow={pct}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        {pct}%
                      </span>
                    )}
                    {df.state === "error" && (
                      <span className="file-item__error-text">
                        {df.error ??
                          t(
                            "The upload failed. Remove the file and add it again.",
                          )}
                      </span>
                    )}
                    {isDone &&
                      df.scanSubmitted &&
                      (df.scanStatus === "pending" ||
                        // A transient scan error is retried on its own.
                        (df.scanStatus === "error" &&
                          df.scanErrorKind !== "file")) &&
                      (draft.scanTimedOut ? (
                        <Tooltip
                          content={t(
                            "This file couldn't be scanned — the scanner may be unavailable. Click to retry.",
                          )}
                          placement="top"
                        >
                          <button
                            type="button"
                            className="file-item__scan file-item__scan--retry"
                            onClick={() => draft.retryScan()}
                            disabled={draft.isRetrying}
                            aria-label={t("Retry scan")}
                          >
                            {draft.isRetrying ? <Spinner /> : <Retry />}
                          </button>
                        </Tooltip>
                      ) : (
                        <span className="file-item__scan file-item__scan--pending">
                          <Spinner />
                          {t("Scanning…")}
                        </span>
                      ))}
                    {isDone &&
                      df.scanStatus === "error" &&
                      df.scanErrorKind === "file" && (
                        <span className="file-item__scan file-item__scan--blocked">
                          <WarningFilled />
                          {t("Could not be scanned")}
                        </span>
                      )}
                    {isDone && df.scanStatus === "clean" && (
                      <Tooltip
                        content={t("Scanned, no virus found")}
                        placement="top"
                      >
                        <span className="file-item__scan file-item__scan--clean">
                          <CheckmarkShield />
                        </span>
                      </Tooltip>
                    )}
                    {isDone && df.scanStatus === "infected" && (
                      <span className="file-item__scan file-item__scan--blocked">
                        <WarningFilled />
                        {t("Virus detected")}
                      </span>
                    )}
                    {isDone &&
                      (df.scanStatus === "too_large" ||
                        df.scanStatus === "unscannable") && (
                        <Tooltip
                          content={t(
                            "This file could not be checked by the antivirus. It will be sent, and the recipient will be told.",
                          )}
                          placement="top"
                        >
                          <span className="file-item__scan file-item__scan--warning">
                            <Warning />
                            {t("Not scanned")}
                          </span>
                        </Tooltip>
                      )}
                  </>
                }
                action={
                  <button
                    type="button"
                    className="transfer-form__file-action"
                    onClick={() => {
                      setFileError(null);
                      setSubmitError(null);
                      void draft.removeFile(df.key);
                    }}
                    disabled={draft.isFinalizing}
                    aria-label={t("Delete")}
                    title={t("Delete")}
                  >
                    <Trash />
                  </button>
                }
              />
            );
          })}
        </ul>
      )}

      {submitError && <Alert type={VariantType.ERROR}>{submitError}</Alert>}

      <Button
        color="brand"
        fullWidth
        onClick={() => void send()}
        disabled={busy || !hasFiles || anyError || scanBlocking}
        icon={busy ? <Spinner size="sm" /> : undefined}
      >
        {draft.isScanning
          ? t("Checking for viruses…")
          : busy
            ? t("Sending…")
            : t("Send the files")}
      </Button>
    </div>
  );
}
