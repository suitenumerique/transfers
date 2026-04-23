import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { openPicker } from "@gouvfr-lasuite/drive-sdk";
import { FolderDrive } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";
import type { DrivePickedItem } from "../api/useTransferDraft";

interface Props {
  onPick: (items: DrivePickedItem[]) => void;
  onError?: (message: string) => void;
  disabled?: boolean;
  // Optional upper bound: reject obviously oversized items up-front for UX.
  // The backend re-checks the per-file and cumulative limits at add-file time.
  maxFileSize?: number;
  // "button" (default) — Cunningham neutral button, used inline with the
  // compact dropzone once files exist. "link" — plain text link with a
  // folder icon, used below the empty dropzone per the design handoff
  // ("avec le service Fichiers").
  variant?: "button" | "link";
}

// Browser-side URL concatenation: backend sends Drive paths as relative
// strings (`/sdk`, `/api/v1.0`); we join them with the base URL before
// handing them to the SDK.
function joinUrl(base: string, path: string): string {
  if (!path) return base;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return base.replace(/\/+$/, "") + "/" + path.replace(/^\/+/, "");
}

// Design note: attachment is a *server-side import* — we pass the Drive
// public permalink (``url_permalink``) to the backend, which streams the
// bytes into our S3 via a celery task. No dl+ul through the browser means
// no tab memory pressure and no throttling, and the file looks identical
// to a browser-uploaded one once the import completes. The tradeoff is
// that the picked Drive item is flipped to public when picked — a
// mechanism owned by Drive itself, not by us.
//
// A hard-copy mode (browser fetches bytes and re-uploads) was tried
// first and rejected: it buffers the full file in tab RAM via `blob()`
// and pins the user's machine in the data path.
export function DriveAttachButton({
  onPick,
  onError,
  disabled,
  maxFileSize,
  variant = "button",
}: Props) {
  const { t } = useTranslation();
  const config = useConfig();
  const [busy, setBusy] = useState(false);

  if (!config.DRIVE) return null;

  const drive = config.DRIVE;

  const handleClick = async () => {
    setBusy(true);
    // The SDK only resolves on `ITEMS_SELECTED` / `CANCEL` messages posted
    // from the Drive picker UI. Closing the popup with the OS X button
    // sends neither — the awaited promise sits forever and `busy` stays
    // true, leaving our button stuck grey. Intercept the popup the SDK
    // opens via `window.open` so we can watch `popup.closed` and treat a
    // user-closed window as a cancel.
    //
    // TODO: remove once the upstream SDK resolves on popup close —
    // suitenumerique/drive:src/frontend/packages/sdk/src/Picker.ts already
    // has a commented-out `watchForClosing` (disabled over a COOP false-
    // positive during cross-origin auth redirects). A fix there ships a
    // `0.0.3`+ and we can drop this wrapper.
    const originalOpen = window.open;
    let popup: Window | null = null;
    window.open = ((...args: Parameters<typeof window.open>) => {
      popup = originalOpen.apply(window, args);
      return popup;
    }) as typeof window.open;
    try {
      const pickerPromise = openPicker({
        url: joinUrl(drive.base_url, drive.sdk_url),
        apiUrl: joinUrl(drive.base_url, drive.api_url),
      });

      const closedByUserPromise = new Promise<{ type: "cancelled" }>(
        (resolve) => {
          const id = window.setInterval(() => {
            if (popup && popup.closed) {
              window.clearInterval(id);
              resolve({ type: "cancelled" });
            }
          }, 300);
          // Clear the watcher if the picker resolves first — otherwise we
          // leak the interval forever.
          pickerPromise.finally(() => window.clearInterval(id));
        },
      );

      const result = await Promise.race([pickerPromise, closedByUserPromise]);
      if (result.type !== "picked" || !result.items) return;

      // Narrow the SDK's Item type to the fields we need. The picker
      // response shape is stable under this subset (tested against the
      // ANCT Drive release on 2026-04-22).
      const items = result.items as unknown as Array<{
        url_permalink: string;
        filename: string;
        size: number;
        mimetype: string;
      }>;

      if (maxFileSize) {
        const oversized = items.find((it) => it.size > maxFileSize);
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

      onPick(
        items.map((it) => ({
          url_permalink: it.url_permalink,
          filename: it.filename,
          size: it.size,
          mimetype: it.mimetype,
        })),
      );
    } catch {
      onError?.(
        t(
          "Could not download from {{app}}. Check that the file is accessible and try again.",
          { app: drive.app_name },
        ),
      );
    } finally {
      window.open = originalOpen;
      setBusy(false);
    }
  };

  if (variant === "link") {
    return (
      <Button
        type="button"
        color="brand"
        variant="tertiary"
        size="small"
        className="drive-attach-link"
        onClick={handleClick}
        disabled={disabled || busy}
        icon={<FolderDrive />}
      >
        {/* Default children rely on the translation files, which all ship
            the key. Inline JSX children would choke on {{app}} (JSX
            reads it as an expression, not an i18next placeholder). */}
        <Trans
          i18nKey="drive.attach_link_label"
          values={{ app: drive.app_name }}
          components={{ strong: <strong /> }}
        />
      </Button>
    );
  }

  return (
    <Button
      type="button"
      color="neutral"
      size="small"
      onClick={handleClick}
      disabled={disabled || busy}
      icon={<FolderDrive />}
    >
      {t("Attach from {{app}}", { app: drive.app_name })}
    </Button>
  );
}
