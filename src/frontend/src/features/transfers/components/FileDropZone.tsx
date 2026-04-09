import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useDropzone } from "react-dropzone";
import { formatFileSize } from "@/features/utils/string-helper";

interface FileDropZoneProps {
  files: File[];
  onChange: (files: File[]) => void;
}

export function FileDropZone({ files, onChange }: FileDropZoneProps) {
  const { t } = useTranslation();

  const onDrop = useCallback(
    (accepted: File[]) => {
      onChange([...files, ...accepted]);
    },
    [files, onChange],
  );

  const removeFile = (index: number) => {
    onChange(files.filter((_, i) => i !== index));
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  return (
    <div className="file-dropzone">
      <div
        {...getRootProps()}
        className={`file-dropzone__area ${isDragActive ? "file-dropzone__area--active" : ""}`}
      >
        <input {...getInputProps()} />
        <p>
          {isDragActive
            ? t("Drop files here...")
            : t("Drag and drop files or click to select")}
        </p>
      </div>
      {files.length > 0 && (
        <ul className="file-dropzone__list">
          {files.map((file, i) => (
            <li key={`${file.name}-${i}`} className="file-dropzone__item">
              <span>{file.name}</span>
              <span className="file-dropzone__size">{formatFileSize(file.size)}</span>
              <button
                type="button"
                className="file-dropzone__remove"
                onClick={() => removeFile(i)}
              >
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
