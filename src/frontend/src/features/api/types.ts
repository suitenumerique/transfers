export type SharingMode = "email" | "link";

export interface TransferRecipient {
  id: string;
  email: string;
  email_sent_at: string | null;
}

export interface TransferListItem {
  id: string;
  title: string;
  status: "active" | "expired" | "revoked";
  sharing_mode: SharingMode;
  sensitive: boolean;
  has_password: boolean;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  file_count: number;
  total_size: number;
  consulted: boolean;
  downloaded: boolean;
}

export interface TransferFile {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  created_at: string;
}

export interface TransferDetail {
  id: string;
  title: string;
  status: "active" | "expired" | "revoked";
  sharing_mode: SharingMode;
  sensitive: boolean;
  has_password: boolean;
  public_token: string | null;
  upload_completed_at: string | null;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  files: TransferFile[];
  recipients: TransferRecipient[];
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

export interface DownloadTransferFull {
  title: string;
  expires_at: string;
  created_at: string;
  files: { id: string; filename: string; size: number; mime_type: string }[];
  owner_name: string;
  owner_email: string;
}
