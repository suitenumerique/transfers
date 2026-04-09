export interface TransferListItem {
  id: string;
  title: string;
  status: "active" | "expired" | "revoked";
  has_password: boolean;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  file_count: number;
  total_size: number;
  recipient_count: number;
}

export interface TransferFile {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  created_at: string;
}

export interface TransferRecipient {
  id: string;
  email: string;
}

export interface TransferDetail {
  id: string;
  title: string;
  message: string;
  status: "active" | "expired" | "revoked";
  has_password: boolean;
  public_token: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  files: TransferFile[];
  recipients: TransferRecipient[];
}

export interface TransferEvent {
  id: string;
  transfer_id: string;
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

export interface DownloadTransferLocked {
  title: string;
  has_password: true;
}

export interface DownloadTransferFull {
  title: string;
  message: string;
  has_password: boolean;
  expires_at: string;
  created_at: string;
  files: { id: string; filename: string; size: number; mime_type: string }[];
  owner_name: string;
  owner_email: string;
}

export type DownloadTransferResponse =
  | DownloadTransferLocked
  | DownloadTransferFull;
