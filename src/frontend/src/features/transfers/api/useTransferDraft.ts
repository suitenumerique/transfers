import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type {
  ScanErrorKind,
  ScanStatus,
  SharingMode,
  TransferDetail,
} from "@/features/api/types";
import {
  ciphertextSize,
  encryptChunk,
  generateTransferKey,
  PLAINTEXT_CHUNK_SIZE,
} from "../upload/e2eCrypto";
import { MultipartUploader } from "../upload/MultipartUploader";

// Eager-upload draft handle.
//
// Every file drop hits the same endpoint: `POST /drafts/add-file/`. The
// first call of a session omits ``draft_id`` — the backend opens a draft
// as a side-effect and echoes the id back. Subsequent drops pass that id
// so their file lands on the same draft. Drop-removals hit
// `/drafts/{id}/remove-file/`. Bytes are pushed to S3 via presigned
// multipart PUTs as soon as the backend descriptor is known — the form is
// free to remain unfilled. `submit()` waits for the upload queue to drain,
// then calls `/drafts/{id}/finalize/` which creates the Transfer and
// reparents the files to it in one atomic step (metadata never flows
// through the draft phase).
//
// When the last file is removed from the draft, the backend cascades the
// draft deletion automatically, so the local reset is purely bookkeeping.

export type DraftFileState =
  | "registering" // POST /drafts/add-file/ in flight
  | "registered" // waiting in queue for the upload pump (local uploads only)
  | "uploading" // MultipartUploader is pushing chunks to S3
  | "importing" // server-side Drive import in progress (celery task)
  | "done" // upload / import succeeded
  | "error"; // registration, upload, or import failed

export interface DraftFile {
  key: string;
  // Local File, present only for browser-uploaded drops. Absent for
  // server-side Drive imports (the bytes never reach the browser).
  file: File | null;
  // Denormalized metadata: mirrors File fields for local drops, comes
  // from the Drive picker for imports. Lets the UI render uniformly.
  name: string;
  size: number;
  mimeType: string;
  // Drive permalink for imported files; empty string otherwise.
  sourceUrl: string;
  backendId: string | null;
  s3Key: string | null;
  uploadId: string | null;
  chunkSize: number | null;
  loaded: number;
  total: number;
  state: DraftFileState;
  // Antivirus verdict, polled once the upload is done. Undefined until the
  // first poll lands. "pending" while clamd is scanning.
  scanStatus?: ScanStatus;
  // When scanStatus is "error": "file" (unscannable, must remove) vs
  // "transient" (retryable). Drives which message the form shows.
  scanErrorKind?: ScanErrorKind;
  error?: string;
}

export interface FinalizeMetadata {
  title?: string;
  expires_in_days?: number;
  sharing_mode?: SharingMode;
  recipients?: string[];
  sensitive?: boolean;
  auto_archive_on_download?: boolean;
}

// Shape of an item returned by the Drive picker after Nathan's fix — the
// public permalink is in ``url_permalink``. Narrowed to what we consume.
export interface DrivePickedItem {
  url_permalink: string;
  filename: string;
  size: number;
  mimetype: string;
}

export interface TransferDraftHandle {
  draftId: string | null;
  files: DraftFile[];
  // URL-safe base64 of the AES-256 key when the draft is E2E-encrypted.
  // Generated lazily on the first add-file call when the caller passes
  // `e2eEncrypted: true`. The caller appends it to the finalized
  // transfer's URL fragment so the recipient can decrypt.
  e2eKeyFragment: string | null;
  // Two-phase submit state:
  // - `isAwaitingUploads`: user clicked Send but uploads are still running.
  //   Auto-finalize is armed but cancellable via `cancelSubmit()` or by
  //   removing any file.
  // - `isFinalizing`: uploads are done and the POST /finalize/ is in flight.
  //   The draft is being turned into a Transfer server-side — no way back.
  isAwaitingUploads: boolean;
  isFinalizing: boolean;
  // True while finalize is blocked on the antivirus scan (backend returns 202
  // until every file is clean). Drives the "checking for viruses" loading step.
  isScanning: boolean;
  error: string | null;
  // Lock the draft as E2E-encrypted. Honoured only on the first add-file
  // call (the mode is set when the draft is born and can't change after).
  // Generates a random key kept in-memory + surfaced via `e2eKeyFragment`.
  setE2eEncrypted: (on: boolean) => void;
  e2eEncrypted: boolean;
  // Bigger-hammer mode change: tear down the existing draft + any uploads,
  // flip the mode, and re-register every file from the local File refs
  // (re-encrypting in the process if the new mode is E2E). Rejects with
  // `restart_blocked_drive` if any file in the draft was imported from
  // Drive — those have no local File to replay.
  restartWithMode: (newMode: boolean) => Promise<void>;
  addFile: (file: File) => void;
  attachFromDrive: (items: DrivePickedItem[]) => void;
  removeFile: (key: string) => void;
  submit: (metadata: FinalizeMetadata) => Promise<TransferDetail>;
  // Disarm a pending auto-finalize. No-op if the draft isn't waiting on
  // uploads. Called when the user edits the draft (title / recipients /
  // file list) while the submit is armed — intent has shifted, the click
  // on "Send" shouldn't commit the current state.
  cancelSubmit: () => void;
  abort: () => Promise<void>;
}

// Sentinel thrown when the user cancels the auto-finalize wait. Callers
// catch this specifically to distinguish an intentional cancel from a
// genuine failure (upload error, finalize HTTP failure, etc.).
export class SubmitCancelledError extends Error {
  constructor() {
    super("Submit cancelled");
    this.name = "SubmitCancelledError";
  }
}

interface AddFileResponse {
  draft_id: string;
  transfer_file_id: string;
  // These three are only present on the local-upload path. Drive imports
  // skip the multipart ceremony (the server-side celery task owns it).
  upload_id?: string;
  s3_key?: string;
  chunk_size?: number;
}

interface DraftDetailResponse {
  id: string;
  files: Array<{
    id: string;
    filename: string;
    size: number;
    mime_type: string;
    state: "uploading" | "importing" | "done";
    source_url: string;
    scan_status: ScanStatus;
    scan_error_kind: ScanErrorKind;
  }>;
}

interface SignPartResponse {
  url: string;
  part_number: number;
}

export function fileKey(f: File): string {
  return `${f.name}|${f.size}|${f.lastModified}`;
}

const POLL_INTERVAL_MS = 200;
// Finalize is gated by the antivirus scan: the backend answers 202 while files
// are still being scanned. Re-poll on that interval, give up after the max.
const SCAN_POLL_INTERVAL_MS = 2000;
const SCAN_MAX_WAIT_MS = 120000;

interface ScanPendingResponse {
  reason: "scan_pending";
  pending_file_ids: string[];
}

export function useTransferDraft(): TransferDraftHandle {
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState<string | null>(null);
  const [files, setFiles] = useState<DraftFile[]>([]);
  const [isAwaitingUploads, setIsAwaitingUploads] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [e2eEncrypted, setE2eEncryptedState] = useState(false);
  const [e2eKeyFragment, setE2eKeyFragment] = useState<string | null>(null);
  // CryptoKey is opaque and non-serialisable; kept off React state so we
  // don't churn the tree when it lands (the fragment string is the only
  // value the UI cares about).
  const e2eKeyRef = useRef<CryptoKey | null>(null);
  const e2eEncryptedRef = useRef(false);

  // Refs mirror state so async work can observe the freshest list without
  // waiting for the next render.
  const draftIdRef = useRef<string | null>(null);
  const filesRef = useRef<DraftFile[]>([]);
  // Promise that resolves with the draft id once the initial POST
  // /drafts/add-file/ succeeds. Second+ drops wait on it before firing
  // add-file, so they don't race multiple "create-draft" requests.
  const draftInitPromiseRef = useRef<Promise<string> | null>(null);
  // The uploader currently pushing chunks, if any.
  const currentUploaderRef = useRef<MultipartUploader | null>(null);
  // Mirror of `isAwaitingUploads` so `removeFile` can know "is the submit
  // armed?" synchronously without waiting for the next render.
  const isAwaitingUploadsRef = useRef(false);
  // Set to true to signal the polling loop to reject with
  // SubmitCancelledError on its next tick. Read by the loop, written by
  // `cancelSubmit()` or by `removeFile()` when the submit is armed.
  const cancelSubmitRef = useRef(false);

  const setAwaitingUploads = useCallback((v: boolean) => {
    isAwaitingUploadsRef.current = v;
    setIsAwaitingUploads(v);
  }, []);

  const writeFiles = useCallback((next: DraftFile[]) => {
    filesRef.current = next;
    setFiles(next);
  }, []);

  const updateFile = useCallback(
    (key: string, patch: Partial<DraftFile>) => {
      writeFiles(
        filesRef.current.map((f) => (f.key === key ? { ...f, ...patch } : f)),
      );
    },
    [writeFiles],
  );

  const resetLocal = useCallback(() => {
    draftIdRef.current = null;
    draftInitPromiseRef.current = null;
    setDraftId(null);
    writeFiles([]);
    // Per-draft crypto state goes (a fresh draft will mint a new key)
    // but the E2E *intent* sticks — removing the last file shouldn't
    // silently flip the user's encryption preference off, and a new
    // submit-cycle starts on a fresh mount with the default anyway.
    e2eKeyRef.current = null;
    setE2eKeyFragment(null);
  }, [writeFiles]);

  const setE2eEncrypted = useCallback(
    (on: boolean) => {
      // Once the draft exists, the mode is frozen — the backend rejects
      // mismatched follow-up add-file calls. Silently ignore the toggle
      // rather than tear the draft down behind the user.
      if (draftIdRef.current !== null) return;
      e2eEncryptedRef.current = on;
      setE2eEncryptedState(on);
      if (!on) {
        e2eKeyRef.current = null;
        setE2eKeyFragment(null);
      }
    },
    [],
  );

  const abortDraft = useCallback(async () => {
    if (currentUploaderRef.current) {
      currentUploaderRef.current.abort();
      currentUploaderRef.current = null;
    }
    const id = draftIdRef.current;
    // Clear first so registrations racing at this moment see no draft and
    // fail their presence-check (they'll see the file is gone too).
    resetLocal();
    if (id) {
      try {
        await apiFetch(`/drafts/${id}/abort/`, { method: "POST" });
      } catch {
        // best-effort; the server cleanup task sweeps stale drafts anyway
      }
    }
  }, [resetLocal]);

  // --- Upload pump ---
  // Runs as an effect: whenever `files` changes, if no uploader is active,
  // pick the first `registered` file and start it. Drive imports never hit
  // this state (they go `registering → importing` on the backend echo), so
  // the pump sees only local uploads with a File attached.
  useEffect(() => {
    if (currentUploaderRef.current) return;
    const next = files.find((f) => f.state === "registered");
    if (!next || !next.backendId || !next.chunkSize || !next.file) return;

    const backendId = next.backendId;
    const chunkSize = next.chunkSize;
    const key = next.key;
    const localFile = next.file;

    // E2E mode: encrypt each plaintext chunk before it leaves the browser.
    // The crypto chunk size MUST equal the multipart chunk size — one S3
    // part = one self-contained AES-GCM chunk (IV ‖ ciphertext ‖ tag), so
    // the recipient's SW can decrypt sequentially without any boundary
    // metadata beyond chunk_size + plaintext_size.
    const e2eKey = e2eEncryptedRef.current ? e2eKeyRef.current : null;
    const transformChunk = e2eKey
      ? async (blob: Blob) => {
          const buf = await blob.arrayBuffer();
          const ct = await encryptChunk(e2eKey, buf);
          // Cast: Blob's `BlobPart` widened to `Uint8Array<ArrayBuffer>`
          // in current lib.dom.d.ts; our ct is `Uint8Array<ArrayBufferLike>`
          // by inference, identical at runtime.
          return new Blob([ct as unknown as BlobPart], {
            type: "application/octet-stream",
          });
        }
      : undefined;
    const ciphertextTotal = e2eKey
      ? ciphertextSize(localFile.size, chunkSize)
      : localFile.size;

    const uploader = new MultipartUploader({
      file: localFile,
      chunkSize,
      parallelism: 4,
      signPart: async (partNumber) => {
        const id = draftIdRef.current;
        if (!id) throw new Error("Draft was aborted");
        const resp = await apiFetch<SignPartResponse>(
          `/drafts/${id}/sign-part/`,
          {
            method: "POST",
            body: JSON.stringify({
              transfer_file_id: backendId,
              part_number: partNumber,
            }),
          },
        );
        return resp.url;
      },
      onProgress: (loaded, total) => {
        updateFile(key, { loaded, total });
      },
      transformChunk,
      totalSize: ciphertextTotal,
    });
    currentUploaderRef.current = uploader;
    updateFile(key, { state: "uploading" });

    uploader
      .upload()
      .then(async (parts) => {
        const id = draftIdRef.current;
        if (!id) throw new Error("Draft was aborted");
        await apiFetch(`/drafts/${id}/complete-upload/`, {
          method: "POST",
          body: JSON.stringify({
            transfer_file_id: backendId,
            parts,
          }),
        });
        updateFile(key, { state: "done", loaded: localFile.size });
      })
      .catch((err) => {
        // Don't leak an error state if the user explicitly aborted the whole
        // draft — the local row is already gone.
        if (!filesRef.current.some((f) => f.key === key)) return;
        updateFile(key, { state: "error", error: String(err) });
        setError(String(err));
        // Leave the draft alive and surface the errored row. The user
        // decides: click Delete on the bad row (retry by re-dropping) or
        // cancel the whole draft. Previously we tore down the draft
        // automatically here, which made the file silently vanish from
        // the UI — indistinguishable from a successful removal.
      })
      .finally(() => {
        currentUploaderRef.current = null;
      });
  }, [files, updateFile]);

  // --- Import poller ---
  // Drive imports run server-side (celery task). We poll the draft endpoint
  // to detect `importing → done` transitions. Started lazily when at least
  // one file is in the `importing` state; stopped as soon as none remain.
  // If a file we believe is importing has disappeared server-side, the
  // task failed → mark it error locally so the UI surfaces it.
  useEffect(() => {
    const hasImporting = files.some((f) => f.state === "importing");
    if (!hasImporting) return;
    const id = draftIdRef.current;
    if (!id) return;

    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      try {
        const resp = await apiFetch<DraftDetailResponse>(`/drafts/${id}/`);
        if (cancelled) return;

        const byBackendId = new Map(resp.files.map((f) => [f.id, f]));
        const localByKey = new Map(
          filesRef.current.map((f) => [f.key, f] as const),
        );

        const next = Array.from(localByKey.values()).map((f) => {
          if (f.state !== "importing") return f;
          if (!f.backendId) return f;
          const server = byBackendId.get(f.backendId);
          if (!server) {
            return {
              ...f,
              state: "error" as DraftFileState,
              error: "Import from Drive failed.",
            };
          }
          if (server.state === "done") {
            return {
              ...f,
              state: "done" as DraftFileState,
              loaded: f.total,
            };
          }
          return f;
        });
        const mutated = next.some((f, i) => {
          const prev = filesRef.current[i];
          return prev && (prev.state !== f.state || prev.loaded !== f.loaded);
        });
        if (mutated) writeFiles(next);
      } catch {
        // Transient errors are fine — the next tick will catch the state.
      }
    };

    const handle = window.setInterval(tick, 2000);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [files, writeFiles]);

  // --- Scan poller ---
  // Once a file's upload is done, its antivirus verdict lands asynchronously
  // (webhook → scan_status). Poll the draft so the form shows "clean" / "virus
  // detected" per file as soon as the scan resolves, without waiting for the
  // user to hit Create. Runs while any done file is still PENDING (or unknown).
  useEffect(() => {
    const needsScan = files.some(
      (f) =>
        f.state === "done" &&
        (f.scanStatus === undefined ||
          f.scanStatus === "pending" ||
          // A transient error auto-retries (reaper / finalize) — keep polling
          // so it flips to clean once the scanner recovers. A file-bound error
          // is terminal, so it doesn't keep us polling.
          (f.scanStatus === "error" && f.scanErrorKind !== "file")),
    );
    if (!needsScan) return;
    const id = draftIdRef.current;
    if (!id) return;

    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      try {
        const resp = await apiFetch<DraftDetailResponse>(`/drafts/${id}/`);
        if (cancelled) return;

        const byBackendId = new Map(resp.files.map((f) => [f.id, f]));
        const next = filesRef.current.map((f) => {
          if (!f.backendId) return f;
          const server = byBackendId.get(f.backendId);
          if (
            !server ||
            (server.scan_status === f.scanStatus &&
              server.scan_error_kind === (f.scanErrorKind ?? ""))
          )
            return f;
          return {
            ...f,
            scanStatus: server.scan_status,
            scanErrorKind: server.scan_error_kind,
          };
        });
        const mutated = next.some(
          (f, i) =>
            filesRef.current[i]?.scanStatus !== f.scanStatus ||
            filesRef.current[i]?.scanErrorKind !== f.scanErrorKind,
        );
        if (mutated) writeFiles(next);
      } catch {
        // Transient errors are fine — the next tick will catch the state.
      }
    };

    const handle = window.setInterval(tick, 2000);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [files, writeFiles]);

  const registerFile = useCallback(
    async (
      draftFile: DraftFile,
      knownDraftId: string | null,
    ): Promise<string | null> => {
      try {
        // `size` is what S3 will store. For E2E we declare the post-encryption
        // size so the backend's head_object check passes; plaintext_size
        // tracks the file's pre-encryption size for the recipient UI.
        const e2eOn = e2eEncryptedRef.current && !draftFile.sourceUrl;
        if (e2eOn && !e2eKeyRef.current) {
          const { cryptoKey, fragment } = await generateTransferKey();
          e2eKeyRef.current = cryptoKey;
          setE2eKeyFragment(fragment);
        }
        const declaredSize = e2eOn
          ? ciphertextSize(draftFile.size, PLAINTEXT_CHUNK_SIZE)
          : draftFile.size;
        const resp = await apiFetch<AddFileResponse>(
          "/drafts/add-file/",
          {
            method: "POST",
            body: JSON.stringify({
              ...(knownDraftId ? { draft_id: knownDraftId } : {}),
              filename: draftFile.name,
              size: declaredSize,
              mime_type: draftFile.mimeType || "application/octet-stream",
              ...(draftFile.sourceUrl
                ? { source_url: draftFile.sourceUrl }
                : {}),
              // E2E params only matter on the call that births the draft;
              // the backend ignores them on follow-ups (the mode is locked).
              ...(e2eOn
                ? {
                    e2e_encrypted: true,
                    encryption_chunk_size: PLAINTEXT_CHUNK_SIZE,
                    plaintext_size: draftFile.size,
                  }
                : {}),
            }),
          },
        );

        // Capture the draft id the FIRST time we see it (or echo back the
        // same one on subsequent calls — the backend always includes it).
        if (draftIdRef.current === null) {
          draftIdRef.current = resp.draft_id;
          setDraftId(resp.draft_id);
        }

        // Reconcile: the user may have removed this file while the POST
        // was in flight. Tell the backend to drop the row (or the whole
        // draft, if this was its only file) so we don't leak.
        if (!filesRef.current.some((f) => f.key === draftFile.key)) {
          try {
            // Special-case: no draft id was known before this call — the
            // file we just created IS the draft's only row, so aborting
            // the whole thing is the right cleanup.
            if (knownDraftId === null) {
              await apiFetch(
                `/drafts/${resp.draft_id}/abort/`,
                { method: "POST" },
              );
              draftIdRef.current = null;
              draftInitPromiseRef.current = null;
              setDraftId(null);
            } else {
              await apiFetch(
                `/drafts/${resp.draft_id}/remove-file/`,
                {
                  method: "POST",
                  body: JSON.stringify({
                    transfer_file_id: resp.transfer_file_id,
                  }),
                },
              );
            }
          } catch {
            // best-effort
          }
          return null;
        }

        // Drive-import path: no upload_id / s3_key / chunk_size echoed
        // back, the celery task owns the multipart from here. Straight to
        // "importing" — the upload pump only runs on "registered" files
        // (which always have a File), so imports skip it entirely.
        if (draftFile.sourceUrl) {
          updateFile(draftFile.key, {
            backendId: resp.transfer_file_id,
            state: "importing",
          });
        } else {
          updateFile(draftFile.key, {
            backendId: resp.transfer_file_id,
            uploadId: resp.upload_id ?? null,
            s3Key: resp.s3_key ?? null,
            chunkSize: resp.chunk_size ?? null,
            state: "registered",
          });
        }
        return resp.draft_id;
      } catch (err) {
        updateFile(draftFile.key, {
          state: "error",
          error: String(err),
        });
        setError(String(err));
        if (knownDraftId === null) {
          // The init attempt failed; clear the lock so the next drop can
          // try again rather than waiting forever on a rejected promise.
          draftInitPromiseRef.current = null;
        }
        throw err;
      }
    },
    [updateFile],
  );

  const startRegistration = useCallback(
    (draftFile: DraftFile) => {
      writeFiles([...filesRef.current, draftFile]);
      setError(null);

      if (
        draftIdRef.current === null &&
        draftInitPromiseRef.current === null
      ) {
        // First attach of the session: this call will birth the draft on
        // the backend. Store the promise so concurrent addFile /
        // attachFromDrive calls wait for the draft id instead of racing
        // multiple "create-draft" requests.
        draftInitPromiseRef.current = registerFile(draftFile, null).then(
          (id) => {
            if (!id) {
              throw new Error("Draft aborted during initialization");
            }
            return id;
          },
        );
        draftInitPromiseRef.current.catch(() => {});
        return;
      }

      void (async () => {
        const id =
          draftIdRef.current ?? (await draftInitPromiseRef.current);
        if (!id) {
          updateFile(draftFile.key, {
            state: "error",
            error: "Draft initialization failed",
          });
          return;
        }
        // Presence check after the await: user may have removed the file
        // while the init was in flight.
        if (!filesRef.current.some((f) => f.key === draftFile.key)) return;
        await registerFile(draftFile, id);
      })();
    },
    [registerFile, updateFile, writeFiles],
  );

  const addFile = useCallback(
    (file: File) => {
      const key = fileKey(file);
      // Guard against duplicate drops sneaking past the caller's dedupe.
      if (filesRef.current.some((f) => f.key === key)) return;

      // Adding a file while the auto-finalize is armed shifts the user's
      // intent — disarm so the newly-added file isn't silently folded
      // into a send they initiated before it existed.
      if (isAwaitingUploadsRef.current) {
        cancelSubmitRef.current = true;
      }

      const draftFile: DraftFile = {
        key,
        file,
        name: file.name,
        size: file.size,
        mimeType: file.type,
        sourceUrl: "",
        backendId: null,
        s3Key: null,
        uploadId: null,
        chunkSize: null,
        loaded: 0,
        total: file.size,
        state: "registering",
      };
      startRegistration(draftFile);
    },
    [startRegistration],
  );

  const attachFromDrive = useCallback(
    (items: DrivePickedItem[]) => {
      for (const item of items) {
        // Dedupe by source url so re-picking the same Drive item is a no-op.
        const key = `drive:${item.url_permalink}`;
        if (filesRef.current.some((f) => f.key === key)) continue;

        // Same reasoning as addFile: a freshly-attached import shouldn't
        // ride on an auto-finalize armed before it was picked.
        if (isAwaitingUploadsRef.current) {
          cancelSubmitRef.current = true;
        }

        const draftFile: DraftFile = {
          key,
          file: null,
          name: item.filename,
          size: item.size,
          mimeType: item.mimetype,
          sourceUrl: item.url_permalink,
          backendId: null,
          s3Key: null,
          uploadId: null,
          chunkSize: null,
          loaded: 0,
          total: item.size,
          state: "registering",
        };
        startRegistration(draftFile);
      }
    },
    [startRegistration],
  );

  const removeFile = useCallback(
    async (key: string) => {
      const target = filesRef.current.find((f) => f.key === key);
      if (!target) return;

      // If the user clicked Send and is now modifying the draft (removing a
      // file / cancelling a live upload), drop the armed auto-finalize —
      // intent has clearly shifted. The polling loop picks this up on its
      // next tick and rejects with SubmitCancelledError.
      if (isAwaitingUploadsRef.current) {
        cancelSubmitRef.current = true;
      }

      // Stop the uploader if this is the file being pushed right now.
      if (currentUploaderRef.current && target.state === "uploading") {
        currentUploaderRef.current.abort();
        currentUploaderRef.current = null;
      }

      const remaining = filesRef.current.filter((f) => f.key !== key);
      writeFiles(remaining);

      // If the file was still in flight to the backend (state=registering),
      // the register call's presence-check will clean up after itself once
      // the POST returns — nothing more to do here.
      if (!target.backendId || !draftIdRef.current) return;

      try {
        await apiFetch(
          `/drafts/${draftIdRef.current}/remove-file/`,
          {
            method: "POST",
            body: JSON.stringify({ transfer_file_id: target.backendId }),
          },
        );
      } catch {
        // best-effort; a 404 means the server already cleaned it up
      }

      // The backend destroys the draft when its last file is removed,
      // so once the local list is empty we just need to drop our handle
      // to it — no explicit abort round-trip.
      if (remaining.length === 0) {
        resetLocal();
      }
    },
    [resetLocal, writeFiles],
  );

  const submit = useCallback(
    async (metadata: FinalizeMetadata): Promise<TransferDetail> => {
      const id = draftIdRef.current;
      if (!id) throw new Error("No draft to submit");
      if (filesRef.current.length === 0) throw new Error("No files");

      cancelSubmitRef.current = false;
      setAwaitingUploads(true);
      try {
        // Wait for every file to reach "done". Polling ref state is fine —
        // the UI already shows per-file progress, and the wait is bounded
        // by the last byte landing in S3. The cancel check comes first so
        // a user-triggered cancel (re-click Send or Remove-file) unblocks
        // within one tick.
        await new Promise<void>((resolve, reject) => {
          const tick = () => {
            if (cancelSubmitRef.current) {
              reject(new SubmitCancelledError());
              return;
            }
            const current = filesRef.current;
            const errored = current.find((f) => f.state === "error");
            if (errored) {
              reject(new Error(errored.error ?? "Upload failed"));
              return;
            }
            if (current.length === 0) {
              reject(new Error("All files removed"));
              return;
            }
            if (current.every((f) => f.state === "done")) {
              resolve();
              return;
            }
            setTimeout(tick, POLL_INTERVAL_MS);
          };
          tick();
        });

        // Past the point of no cancel — flip the state so the UI locks
        // everything for the (short) /finalize/ round-trip.
        setAwaitingUploads(false);
        setIsFinalizing(true);

        // Metadata is frozen here — the draft held nothing but files, and
        // finalize is the one write that creates the Transfer with its
        // title / sharing mode / recipients / expiry in a single atomic
        // step. The returned Transfer has a *different* id from the draft.
        // Finalize is antivirus-gated: 200 = transfer created, 202 = files
        // still scanning (poll again), 4xx with reason "scan_blocked" = a file
        // was rejected (thrown by apiFetch, surfaced to the caller).
        // E2E + email: pass the URL fragment along so the email task can
        // embed the full decryption link. Skipped for link mode (the
        // sender's browser owns the fragment) and for non-E2E transfers.
        const fragment = e2eKeyFragment;
        const finalizeBody = {
          ...metadata,
          ...(fragment && metadata.sharing_mode === "email"
            ? { key_fragment: fragment }
            : {}),
        };
        const scanDeadline = Date.now() + SCAN_MAX_WAIT_MS;
        let finalized: TransferDetail;
        for (;;) {
          const resp = await apiFetch<TransferDetail | ScanPendingResponse>(
            `/drafts/${id}/finalize/`,
            {
              method: "POST",
              body: JSON.stringify(finalizeBody),
            },
          );
          if (resp && (resp as ScanPendingResponse).reason === "scan_pending") {
            if (Date.now() > scanDeadline) {
              throw new Error("scan_timeout");
            }
            setIsScanning(true);
            await new Promise((r) => setTimeout(r, SCAN_POLL_INTERVAL_MS));
            continue;
          }
          finalized = resp as TransferDetail;
          break;
        }

        queryClient.invalidateQueries({ queryKey: ["transfers"] });
        resetLocal();
        return finalized;
      } finally {
        setAwaitingUploads(false);
        setIsFinalizing(false);
        setIsScanning(false);
        cancelSubmitRef.current = false;
      }
    },
    [queryClient, resetLocal, setAwaitingUploads, e2eKeyFragment],
  );

  const cancelSubmit = useCallback(() => {
    if (isAwaitingUploadsRef.current) {
      cancelSubmitRef.current = true;
    }
  }, []);

  const restartWithMode = useCallback(
    async (newMode: boolean): Promise<void> => {
      // Snapshot the local Files first — abortDraft() empties filesRef
      // by way of resetLocal, and we need the originals to re-feed
      // addFile after the wipe.
      const snapshot = filesRef.current.map((f) => f.file).filter((f): f is File => f !== null);
      // Imports from Drive have `file === null` (the bytes live server-
      // side and were never in the browser). Refuse to replay if any
      // are present, since we'd silently drop them.
      if (snapshot.length !== filesRef.current.length) {
        const err = new Error("restart_blocked_drive");
        err.name = "RestartBlockedError";
        throw err;
      }
      await abortDraft();
      // abortDraft -> resetLocal cleared draftIdRef, so setE2eEncrypted
      // is allowed to flip the intent. The cryptoKey is also reset so
      // the next registerFile mints a fresh one.
      setE2eEncrypted(newMode);
      for (const f of snapshot) {
        addFile(f);
      }
    },
    [abortDraft, setE2eEncrypted, addFile],
  );

  return {
    draftId,
    files,
    isAwaitingUploads,
    isFinalizing,
    isScanning,
    error,
    e2eEncrypted,
    e2eKeyFragment,
    setE2eEncrypted,
    restartWithMode,
    addFile,
    attachFromDrive,
    removeFile,
    submit,
    cancelSubmit,
    abort: abortDraft,
  };
}
