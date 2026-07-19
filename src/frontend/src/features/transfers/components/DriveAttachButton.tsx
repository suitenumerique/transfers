import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { openPicker } from "@gouvfr-lasuite/drive-sdk";
import { FolderDrive } from "@gouvfr-lasuite/ui-kit/icons";
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
    try {
      // Known UX wart: the SDK resolves only on ITEMS_SELECTED / CANCEL
      // messages from inside the Drive picker UI — closing the popup via
      // the OS X button leaves this promise pending forever, and the
      // button stays stuck grey until the tab is reloaded. A previous
      // workaround watched `popup.closed` to force-cancel, but that
      // produced false positives under COOP once the popup redirected
      // cross-origin through ProConnect, wrecking the integration
      // entirely. The fix lives upstream in
      // suitenumerique/drive:src/frontend/packages/sdk/src/Picker.ts
      // (a `watchForClosing` helper is already drafted + commented-out
      // there pending a COOP-safe resolution).
      const result = await openPicker({
        url: joinUrl(drive.base_url, drive.sdk_url),
        apiUrl: joinUrl(drive.base_url, drive.api_url),
      });
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
