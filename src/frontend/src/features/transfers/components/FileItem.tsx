import type { ReactNode } from "react";

// Single-row file primitive shared between the upload form and the transfer
// recap / detail view: [icon] [name · size (extras...)] ···············[action].
//
// The uploader and the recap render functionally different icons (progress
// ring / check / error for the upload, doc or folder tile for the recap)
// and different actions (Cancel/Delete text for upload, Download button for
// recap) — but the row layout, padding, border, and label typography are
// identical. Kept as a thin presentational shell so both call sites share
// the same visual treatment without pulling in each other's state machines.

export type FileItemState = "default" | "uploading" | "done" | "error";

export interface FileItemProps {
  icon: ReactNode;
  name: string;
  size: string; // pre-formatted, e.g. "248 MB"
  // Inline extras shown after size — percent while uploading, "Importing..."
  // during a Fichiers import, an error message, etc. Rendered inside the
  // label row so ellipsis / wrapping stays consistent.
  extras?: ReactNode;
  // Right-aligned action slot — can be a Cunningham Button or a plain
  // <button>. Left empty on read-only rows.
  action?: ReactNode;
  // Drives the icon color (brand / success / error). Doesn't affect the
  // row chrome; status is communicated by the icon, not by row tinting.
  state?: FileItemState;
  className?: string;
}

export function FileItem({
  icon,
  name,
  size,
  extras,
  action,
  state = "default",
  className,
}: FileItemProps) {
  return (
    <li className={`file-item file-item--${state}${className ? ` ${className}` : ""}`}>
      <span className="file-item__icon" aria-hidden="true">
        {icon}
      </span>
      <span className="file-item__label">
        <span className="file-item__name">{name}</span>
        <span className="file-item__sep">·</span>
        <span className="file-item__size">{size}</span>
        {extras}
      </span>
      {action}
    </li>
  );
}
