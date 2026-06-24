export type SharingMode = "email" | "link";

export type TransferStatus =
  | "active"
  | "pending_file_deletion"
  | "deactivated";

export type DeactivationReason = "manual" | "expired" | "first_download";

export interface TransferRecipient {
  id: string;
  email: string;
  email_sent_at: string | null;
}

export interface TransferListItem {
  id: string;
  title: string;
  status: TransferStatus;
  sharing_mode: SharingMode;
  sensitive: boolean;
  expires_at: string;
  deactivated_at: string | null;
  deactivation_reason: DeactivationReason | null;
  created_at: string;
  file_count: number;
  total_size: number;
  consulted: boolean;
  downloaded: boolean;
  auto_archive_on_download: boolean;
  pending_deletion_at: string | null;
}

export interface TransferFile {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  created_at: string;
  scan_status: ScanStatus;
  scan_error_kind: ScanErrorKind;
}

export interface TransferDetail {
  id: string;
  title: string;
  status: TransferStatus;
  sharing_mode: SharingMode;
  sensitive: boolean;
  public_token: string | null;
  upload_completed_at: string | null;
  expires_at: string;
  deactivated_at: string | null;
  deactivation_reason: DeactivationReason | null;
  created_at: string;
  // Set by the recipient-invitation task once it has iterated every
  // recipient (whether their delivery succeeded or not). Used to leave the
  // form's "sending…" polling state.
  notifications_completed_at: string | null;
  files: TransferFile[];
  recipients: TransferRecipient[];
  auto_archive_on_download: boolean;
  pending_deletion_at: string | null;
}

export interface TransferEvent {
  id: string;
  transfer_id: string;
  event_type: string;
  actor_type: "agent" | "external";
  actor_id: string | null;
  ip: string | null;
  user_agent: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type ScanStatus =
  | "pending"
  | "clean"
  | "infected"
  | "error"
  | "skipped"
  | "too_large";

// Set only when scan_status is "error". "file" = the file itself can't be
// scanned (remove it); "transient" = an infra hiccup a retry may clear.
export type ScanErrorKind = "transient" | "file" | "";

export interface DownloadTransferFile {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  scan_status: ScanStatus;
}

export interface DownloadTransferFull {
  title: string;
  expires_at: string;
  created_at: string;
  files: DownloadTransferFile[];
  owner_name: string;
  is_owner: boolean;
  sharing_mode: SharingMode;
  auto_archive_on_download: boolean;
}
