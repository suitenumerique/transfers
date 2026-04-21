import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { openPicker, type Item } from "@gouvfr-lasuite/drive-sdk";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";

interface Props {
  onPick: (files: File[]) => void;
  onError?: (message: string) => void;
  disabled?: boolean;
  // Optional upper bound: reject obviously oversized items before we pay
  // the bytes over the wire. TransferForm re-checks the aggregate after
  // merge, so this is purely a UX shortcut.
  maxFileSize?: number;
}

// Browser-side URL concatenation: backend sends Drive paths as relative
// strings (`/sdk`, `/api/v1.0`); we join them with the base URL before
// handing them to the SDK.
function joinUrl(base: string, path: string): string {
  if (!path) return base;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return base.replace(/\/+$/, "") + "/" + path.replace(/^\/+/, "");
}

// Design note: this component performs a *hard copy*. We fetch the picked
// items' bytes from Drive and re-upload them to our own S3 via the same
// multipart flow as local drops. A reference-based model was considered
// and rejected because (1) Drive & Transferts TTLs don't match, (2) link
// recipients usually lack Drive accounts, (3) Drive doesn't expose scoped
// un-authenticated download URLs today. Keep this as hard copy — if a
// future reference mode is ever needed, add it as a second action,
// don't replace this.
export function DriveAttachButton({
  onPick,
  onError,
  disabled,
  maxFileSize,
}: Props) {
  const { t } = useTranslation();
  const config = useConfig();
  const [busy, setBusy] = useState(false);

  if (!config.DRIVE) return null;

  const drive = config.DRIVE;

  const handleClick = async () => {
    setBusy(true);
    try {
      const result = await openPicker({
        url: joinUrl(drive.base_url, drive.sdk_url),
        apiUrl: joinUrl(drive.base_url, drive.api_url),
      });
      if (result.type !== "picked" || !result.items) return;

      // Up-front size guard. Avoids downloading 20 GiB just to discard at
      // TransferForm's merge-time limit check.
      if (maxFileSize) {
        const oversized = result.items.find((it) => it.size > maxFileSize);
        if (oversized) {
          onError?.(
            t(
              "Could not download from {{app}}. Check that the file is accessible and try again.",
              { app: drive.app_name },
            ),
          );
          return;
        }
      }

      // Sequential download: cap resident memory at ~1 blob + 1 File so
      // users picking several large files don't OOM the tab. Also means
      // the session cookie / CORS headers are exercised per-request.
      //
      // `credentials: "include"` is REQUIRED: Drive's `item.url` points
      // to the authenticated media route, not an S3 pre-signed URL.
      const files: File[] = [];
      for (const item of result.items as Item[]) {
        const res = await fetch(item.url, { credentials: "include" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        files.push(
          new File([blob], item.title, {
            type: blob.type || "application/octet-stream",
          }),
        );
      }
      onPick(files);
    } catch {
      onError?.(
        t(
          "Could not download from {{app}}. Check that the file is accessible and try again.",
          { app: drive.app_name },
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      type="button"
      color="neutral"
      size="small"
      onClick={handleClick}
      disabled={disabled || busy}
      icon={<Icon name={busy ? "hourglass_empty" : "folder_open"} />}
    >
      {busy
        ? t("Downloading from {{app}}...", { app: drive.app_name })
        : t("Attach from {{app}}", { app: drive.app_name })}
    </Button>
  );
}
