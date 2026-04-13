import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDropzone } from "react-dropzone";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { formatFileSize } from "@/features/utils/string-helper";

interface FileDropZoneProps {
  files: File[];
  onChange: (files: File[]) => void;
  maxFiles?: number;
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

export function FileDropZone({ files, onChange, maxFiles }: FileDropZoneProps) {
  const { t } = useTranslation();
  const windowDragging = useWindowFileDrag();

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (maxFiles === 1) {
        onChange(accepted.slice(0, 1));
      } else {
        onChange([...files, ...accepted]);
      }
    },
    [files, onChange, maxFiles],
  );

  const removeFile = (index: number) => {
    onChange(files.filter((_, i) => i !== index));
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    maxFiles,
  });

  const expanded = windowDragging || isDragActive;

  return (
    <div className="file-dropzone">
      <div
        {...getRootProps()}
        className={`file-dropzone__area${
          expanded ? " file-dropzone__area--expanded" : ""
        }${isDragActive ? " file-dropzone__area--active" : ""}`}
      >
        <input {...getInputProps()} />
        <div className="file-dropzone__cta">
          <p className="file-dropzone__headline">
            {isDragActive
              ? t("Drop it to get started")
              : t("Drop your file here")}
          </p>
          <p className="file-dropzone__hint">
            {isDragActive
              ? t("Release to upload")
              : t("or click anywhere to browse")}
          </p>
        </div>
      </div>
      {files.length > 0 && (
        <ul className="file-dropzone__list">
          {files.map((file, i) => (
            <li key={`${file.name}-${i}`} className="file-dropzone__item">
              <span>{file.name}</span>
              <span className="file-dropzone__size">
                {formatFileSize(file.size)}
              </span>
              <Button
                type="button"
                size="small"
                color="neutral"
                onClick={() => removeFile(i)}
                aria-label={t("Remove")}
              >
                &times;
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
