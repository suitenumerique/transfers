export type SharingMode = "email" | "link";

export type TransferStatus =
  | "active"
  | "pending_file_deletion"
  | "deactivated";

export type DeactivationReason = "manual" | "expired" | "first_download";

// What we can honestly observe about a recipient. There is no "received":
// the relay accepting the message says nothing about the mailbox, and we
// don't do read tracking. "opened" / "downloaded" ride on the personal
// ``?r=<token>`` in the emailed link — a copied link attributes to nobody.
export type RecipientStatus =
  | "sending"
  | "failed"
  | "sent"
  | "opened"
  | "downloaded";

export interface TransferRecipient {
  id: string;
  email: string;
  email_sent_at: string | null;
  status: RecipientStatus;
  opened_at: string | null;
  downloaded_at: string | null;
  // Distinct files this recipient has fetched at least once; compare to
  // ``files.length`` for "2 of 3".
  downloaded_file_count: number;
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
  // Every transfer is encrypted; ``confidential`` marks the ones whose key
  // we never hold (the recipient supplies it from the link fragment or by
  // pasting it). Non-confidential transfers decrypt transparently because
  // the backend serves the key.
  confidential: boolean;
}

export interface TransferFile {
  id: string;
  filename: string;
  size: number;
  // Plaintext size for encrypted files; null otherwise. UIs should
  // fall back to `size` when null. For encryption, `size` is the ciphertext size
  // that sits in S3 (plaintext + per-chunk GCM overhead).
  plaintext_size: number | null;
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
  // Opt-in: the sender gets one email per recipient, the first time that
  // recipient has downloaded every file.
  notify_on_download: boolean;
  pending_deletion_at: string | null;
  confidential: boolean;
  // Plaintext bytes per crypto chunk. Null only for legacy transfers
  // created before encryption was mandatory.
  encryption_chunk_size: number | null;
}

export interface TransferEvent {
  id: string;
  transfer_id: string;
  // Set on LINK_OPENED / FILE_DOWNLOADED reached through a recipient's
  // personal link, and on EMAIL_SENT; null for anonymous visits.
  recipient_id: string | null;
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
  plaintext_size: number | null;
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
  // Sender opted into download receipts. Shown to the owner on their own
  // download page (with ``?r=``) to say their visit won't trigger one.
  notify_on_download: boolean;
  confidential: boolean;
  encryption_chunk_size: number | null;
  // URL-safe base64 of the AES key, served for non-confidential transfers so
  // the SW decrypts transparently. Empty for confidential transfers (the key
  // never reached us) and legacy plaintext transfers.
  encryption_key: string;
}
