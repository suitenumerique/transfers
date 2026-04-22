import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDropzone } from "react-dropzone";
import { CloudArrow, FileError } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";

interface FileDropZoneProps {
  onChange: (files: File[]) => void;
  // When set, the dropzone swaps its cloud+hint for an error state
  // (red dashed border, red tinted background, FileError icon + message)
  // so the user can't miss the rejection reason. The parent is
  // responsible for clearing the error on the next add/remove.
  errorMessage?: string | null;
}

function formatMaxSize(bytes: number): string {
  const gb = bytes / (1024 * 1024 * 1024);
  if (gb >= 1) return `${Math.round(gb)} Go`;
  const mb = bytes / (1024 * 1024);
  return `${Math.round(mb)} Mo`;
}

// True when a drag-and-drop sequence carrying files is active anywhere on
// the page. Used to expand the dropzone so it's obvious where to drop.
function useWindowFileDrag(): boolean {
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    let depth = 0;

    const hasFiles = (event: DragEvent) =>
      Array.from(event.dataTransfer?.types ?? []).includes("Files");

    const onEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth += 1;
      setDragging(true);
    };

    const onLeave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };

    const onDrop = () => {
      depth = 0;
      setDragging(false);
    };

    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);

    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  return dragging;
}

export function FileDropZone({ onChange, errorMessage }: FileDropZoneProps) {
  const { t } = useTranslation();
  const config = useConfig();
  const windowDragging = useWindowFileDrag();
  const hasError = Boolean(errorMessage);

  const onDrop = useCallback(
    (accepted: File[]) => {
      onChange(accepted);
    },
    [onChange],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
  });

  const expanded = windowDragging || isDragActive;

  return (
    <div className="file-dropzone">
      <div
        {...getRootProps()}
        className={`file-dropzone__area${
          expanded ? " file-dropzone__area--expanded" : ""
        }${isDragActive ? " file-dropzone__area--active" : ""}${
          hasError ? " file-dropzone__area--error" : ""
        }`}
      >
        <input {...getInputProps()} />
        {hasError ? (
          <div className="file-dropzone__cta">
            <FileError className="file-dropzone__icon file-dropzone__icon--error" />
            <p className="file-dropzone__title file-dropzone__title--error">
              {errorMessage}
            </p>
            <p className="file-dropzone__title">
              <span className="file-dropzone__title-strong">
                {t("Click to upload")}
              </span>{" "}
              <span className="file-dropzone__title-muted">
                {t("or drag and drop")}
              </span>
            </p>
            <p className="file-dropzone__hint">
              {t("Max {{size}}", {
                size: formatMaxSize(config.TRANSFER_MAX_TOTAL_SIZE),
              })}
            </p>
          </div>
        ) : (
          <div className="file-dropzone__cta">
            <CloudArrow size={32} className="file-dropzone__icon" />
            <p className="file-dropzone__title">
              {isDragActive ? (
                t("Release to upload")
              ) : (
                <>
                  <span className="file-dropzone__title-strong">
                    {t("Click to upload")}
                  </span>{" "}
                  <span className="file-dropzone__title-muted">
                    {t("or drag and drop")}
                  </span>
                </>
              )}
            </p>
            <p className="file-dropzone__hint">
              {t("Max {{size}}", {
                size: formatMaxSize(config.TRANSFER_MAX_TOTAL_SIZE),
              })}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
