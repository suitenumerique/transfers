import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDropzone } from "react-dropzone";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";

interface FileDropZoneProps {
  onChange: (files: File[]) => void;
  compact?: boolean;
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

export function FileDropZone({ onChange, compact = false }: FileDropZoneProps) {
  const { t } = useTranslation();
  const config = useConfig();
  const windowDragging = useWindowFileDrag();

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
    <div className={`file-dropzone${compact ? " file-dropzone--compact" : ""}`}>
      <div
        {...getRootProps()}
        className={`file-dropzone__area${
          compact ? " file-dropzone__area--compact" : ""
        }${expanded ? " file-dropzone__area--expanded" : ""}${
          isDragActive ? " file-dropzone__area--active" : ""
        }`}
      >
        <input {...getInputProps()} />
        {compact ? (
          <>
            <span
              className="file-dropzone__icon-tile"
              aria-hidden="true"
            >
              <Icon name="add" />
            </span>
            <div className="file-dropzone__compact-text">
              <p className="file-dropzone__headline">
                <span className="file-dropzone__cta-link">
                  {t("Add an item")}
                </span>
                <span className="file-dropzone__cta-muted">
                  {" "}
                  {t("or drag and drop")}
                </span>
              </p>
              <p className="file-dropzone__hint">
                {t("Max {{size}}", {
                  size: formatMaxSize(config.TRANSFER_MAX_TOTAL_SIZE),
                })}
              </p>
            </div>
          </>
        ) : (
          <div className="file-dropzone__cta">
            <Icon name="cloud_upload" className="file-dropzone__icon" />
            <p className="file-dropzone__headline">
              {isDragActive
                ? t("Release to upload")
                : t("Click to upload or drag and drop")}
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
