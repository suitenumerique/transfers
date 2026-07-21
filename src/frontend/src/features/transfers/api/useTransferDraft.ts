import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type {
  ScanErrorKind,
  ScanStatus,
  SharingMode,
  TransferDetail,
} from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import {
  aadForChunk,
  ciphertextSize,
  encryptChunk,
  generateTransferKey,
  totalParts,
} from "../upload/encryption";
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
  // first poll lands.
  scanStatus?: ScanStatus;
  // When scanStatus is "error": "file" (unscannable, must remove) vs
  // "transient" (retryable). Drives which message the form shows.
  scanErrorKind?: ScanErrorKind;
  // Whether a scan is actually running. "pending" alone is ambiguous: before
  // Send, files sit pending with no scan in flight (the key isn't sent yet).
  scanSubmitted?: boolean;
  error?: string;
}

export interface FinalizeMetadata {
  title?: string;
  expires_in_days?: number;
  sharing_mode?: SharingMode;
  recipients?: string[];
  sensitive?: boolean;
  auto_archive_on_download?: boolean;
  // When true, the decryption key is NOT sent to the backend: the recipient
  // supplies it from the link fragment or by pasting it. When false (normal),
  // the key is posted at finalize so the backend can serve it to recipients
  // and encrypt any Drive imports server-side.
  confidential?: boolean;
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
  // URL-safe base64 of the AES-256 key. Every transfer is encrypted, so this
  // is generated on the first add-file call. For confidential transfers the
  // caller appends it to the URL fragment (link) or surfaces it for the
  // sender to share out-of-band (email); for normal transfers it is posted
  // to the backend at finalize instead.
  keyFragment: string | null;
  // Synchronous mirror of ``keyFragment`` for callers that need to snapshot
  // the value before ``submit()``'s reset clears it — a render may not have
  // flushed between ``setKeyFragment`` and the click that fires submit, so
  // the state ``keyFragment`` above can still be null in that window.
  keyFragmentRef: { readonly current: string | null };
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
  // True once the background scan poller has waited SCAN_MAX_WAIT_MS without a
  // verdict (scanner likely down). Polling is stopped; `retryScan` re-arms it.
  scanTimedOut: boolean;
  retryScan: () => void;
  // True while a `retryScan` request is in flight — used to disable the retry
  // affordance so a second click can't fire an overlapping re-submit.
  isRetrying: boolean;
  // True while finalize is importing Drive files server-side (202 loop).
  isImportingDrive: boolean;
  // Per-file progress for the current Drive import — refreshed on every
  // finalize poll while ``isImportingDrive`` is true. Empty otherwise.
  driveImportProgress: DriveImportProgress[];
  error: string | null;
  // Confidentiality is chosen at finalize, not locked at draft creation, so
  // this is a free toggle: the ciphertext is identical either way and the key
  // is only ever sent to the backend for a non-confidential finalize.
  setConfidential: (on: boolean) => void;
  confidential: boolean;
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
    scan_submitted: boolean;
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
// A Drive import scales with file size and routinely outlives a scan, so it
// gets its own ceiling — the scan budget would abort healthy large imports.
const DRIVE_IMPORT_MAX_WAIT_MS = 900000;
// Drive imports run for minutes, not seconds — a 2s poll would hammer
// finalize (each hit takes the draft lock and re-checks per-file state)
// without pulling the result any sooner. Start at the scan interval so
// small imports still surface quickly, then double up to the cap.
const DRIVE_IMPORT_POLL_INITIAL_MS = SCAN_POLL_INTERVAL_MS;
const DRIVE_IMPORT_POLL_MAX_MS = 15000;

export interface DriveImportProgress {
  file_id: string;
  filename: string;
  // Plaintext bytes streamed into S3 so far by the server-side import
  // task. Divide by ``plaintext_size`` for a progress percentage. 0
  // before the first chunk lands.
  bytes_imported: number;
  plaintext_size: number;
}

interface FinalizePendingResponse {
  reason: "scan_pending" | "drive_importing";
  pending_file_ids: string[];
  // Only populated on ``drive_importing`` — one entry per file whose
  // server-side import hasn't yet set ``upload_completed_at``.
  import_progress?: DriveImportProgress[];
}

export function useTransferDraft(): TransferDraftHandle {
  const queryClient = useQueryClient();
  // Canonical chunk size for the whole upload + encryption pipeline. Pulled from
  // /config/ so we can never disagree with the backend (which imposes its
  // own ``settings.TRANSFER_CHUNK_SIZE`` on encryption drafts) about where one
  // crypto chunk ends and the next begins.
  const config = useConfig();
  const chunkSizeFromConfig = config.TRANSFER_CHUNK_SIZE;
  const [draftId, setDraftId] = useState<string | null>(null);
  const [files, setFiles] = useState<DraftFile[]>([]);
  const [isAwaitingUploads, setIsAwaitingUploads] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  // The background scan poller gives up after SCAN_MAX_WAIT_MS so a durably
  // unreachable scanner doesn't leave the form polling /drafts/ forever. The
  // backend reaper keeps re-submitting, so the file still self-heals once the
  // scanner recovers — the user just re-arms polling via `retryScan`.
  const [scanTimedOut, setScanTimedOut] = useState(false);
  const scanDeadlineRef = useRef<number | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  // Ref guard mirrors `isRetrying` so overlapping calls are rejected without
  // waiting for the state to flush.
  const isRetryingRef = useRef(false);
  const [isImportingDrive, setIsImportingDrive] = useState(false);
  const [driveImportProgress, setDriveImportProgress] = useState<
    DriveImportProgress[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [confidential, setConfidentialState] = useState(false);
  const [keyFragment, setKeyFragment] = useState<string | null>(null);
  // CryptoKey is opaque and non-serialisable; kept off React state so we
  // don't churn the tree when it lands (the fragment string is the only
  // value the UI cares about).
  const encryptionKeyRef = useRef<CryptoKey | null>(null);
  // Synchronous mirror of `keyFragment`: submit would otherwise read a stale
  // null from its closure if Send is clicked before the render flushes.
  const keyFragmentRef = useRef<string | null>(null);
  const confidentialRef = useRef(false);

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
    // Per-draft crypto state goes (a fresh draft mints a new key). The
    // confidential *intent* sticks — removing the last file shouldn't
    // silently flip the user's preference.
    encryptionKeyRef.current = null;
    keyFragmentRef.current = null;
    setKeyFragment(null);
  }, [writeFiles]);

  const setConfidential = useCallback((on: boolean) => {
    // Free toggle: confidentiality is decided at finalize, so flipping it
    // before send costs nothing (identical ciphertext, key withheld or not).
    // The encryption key itself is always generated and kept — only whether
    // it is posted to the backend at finalize changes.
    confidentialRef.current = on;
    setConfidentialState(on);
  }, []);

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

    // Every transfer is encrypted, so every chunk is encrypted before it
    // leaves the browser. The crypto chunk size MUST equal the multipart
    // chunk size — one S3 part = one self-contained AES-GCM chunk
    // (IV ‖ ciphertext ‖ tag), so the recipient's SW can decrypt
    // sequentially without any boundary metadata beyond chunk_size +
    // plaintext_size. The AAD binds each chunk to its (file, part)
    // position, so storage tampering cannot swap or reorder chunks without
    // breaking GCM tag verification. The key is generated at first add-file
    // and always present here.
    const encryptionKey = encryptionKeyRef.current;
    if (!encryptionKey) return;
    // Total chunks the wire format will emit — bound into every chunk's
    // AAD (as ``:parts``) so the recipient SW and the file-scanner both
    // detect trailing truncation. Must match ``ciphertextSize`` — same
    // formula, same zero-plaintext floor.
    const parts = totalParts(localFile.size, chunkSize);
    const transformChunk = async (blob: Blob, partNumber: number) => {
      const buf = await blob.arrayBuffer();
      const ct = await encryptChunk(
        encryptionKey,
        buf,
        aadForChunk(backendId, partNumber, parts),
      );
      // Cast: Blob's `BlobPart` widened to `Uint8Array<ArrayBuffer>`
      // in current lib.dom.d.ts; our ct is `Uint8Array<ArrayBufferLike>`
      // by inference, identical at runtime.
      return new Blob([ct as unknown as BlobPart], {
        type: "application/octet-stream",
      });
    };
    const ciphertextTotal = ciphertextSize(localFile.size, chunkSize);

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

  // Drive imports no longer run during the draft phase — they're deferred
  // to finalize (the backend needs the key, which only arrives then for a
  // non-confidential transfer). A Drive file is marked ``done`` on
  // registration (ready to send); the finalize 202 loop reports its
  // server-side import progress.

  // --- Scan poller ---
  // Verdicts land asynchronously (webhook → scan_status), so poll to show them
  // per file. Only for scans actually in flight: before Send nothing is
  // scanning, and polling then would spin forever and trip a bogus timeout.
  // Compress the fields the poll depends on into a stable string so the
  // effect below re-runs only when one of them actually changes. Chunk
  // upload progress updates ``loaded`` many times per second and would
  // otherwise re-arm the interval + fire an immediate poll on every
  // progress tick; ``filesRef.current`` inside the effect still reads
  // the fresh file list when we need to apply the response.
  const scanSignal = useMemo(
    () =>
      files
        .map(
          (f) =>
            `${f.backendId ?? ""}:${f.state}:${f.scanStatus ?? ""}:` +
            `${f.scanErrorKind ?? ""}:${f.scanSubmitted ?? ""}`,
        )
        .join("|"),
    [files],
  );

  useEffect(() => {
    const needsScan =
      // Poll at least once after an upload lands, to learn the file's scan
      // state at all (we can't know whether a scan is running until we ask).
      files.some((f) => f.state === "done" && f.scanStatus === undefined) ||
      // Finalize is currently blocked on the scan it just launched.
      isScanning ||
      // A scan the backend has actually submitted is still unresolved. A
      // transient error auto-retries (reaper / rescan) — keep polling so it
      // flips to clean once the scanner recovers. A file-bound error is
      // terminal, so it doesn't keep us polling.
      files.some(
        (f) =>
          f.state === "done" &&
          f.scanSubmitted === true &&
          (f.scanStatus === "pending" ||
            (f.scanStatus === "error" && f.scanErrorKind !== "file")),
      );
    if (!needsScan) {
      // Nothing left to wait on (resolved, or the stuck file was removed) —
      // reset the deadline and clear any timed-out notice so the next batch
      // starts clean. This is a deliberate reset-on-batch-change: leaving a
      // stale `scanTimedOut` would block polling of a freshly added file.
      scanDeadlineRef.current = null;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (scanTimedOut) setScanTimedOut(false);
      return;
    }
    // Stopped after timing out: stay put until the user hits retry.
    if (scanTimedOut) return;
    const id = draftIdRef.current;
    if (!id) return;

    // Anchor the deadline the first time we start waiting on this batch; it
    // survives re-renders (the effect re-runs whenever `files` changes) because
    // it lives in a ref, so unrelated file edits don't reset the clock.
    if (scanDeadlineRef.current === null) {
      scanDeadlineRef.current = Date.now() + SCAN_MAX_WAIT_MS;
    }

    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      if (Date.now() > scanDeadlineRef.current!) {
        setScanTimedOut(true);
        return;
      }
      try {
        const resp = await apiFetch<DraftDetailResponse>(`/drafts/${id}/`);
        // Do NOT bail on ``cancelled`` here — this effect re-runs on every
        // ``files`` change (each upload completion), so a strict cancel
        // would drop the response of a poll started for file N whenever
        // file N+1 finishes uploading during the round-trip. With three
        // files completing in quick succession only the last poll's write
        // would land, and all the intermediate badges would appear at once
        // at the end. The mapping below reads ``filesRef.current`` (always
        // fresh) and the ``state !== "done"`` guard skips any file that
        // hasn't completed client-side yet, so applying an in-flight
        // response is safe. ``cancelled`` still stops the *next* ticks
        // (interval was cleared in the cleanup).

        const byBackendId = new Map(resp.files.map((f) => [f.id, f]));
        const next = filesRef.current.map((f) => {
          if (!f.backendId) return f;
          const server = byBackendId.get(f.backendId);
          if (!server) return f;
          // Skip scan-status propagation while this file is still uploading
          // client-side. A row that hasn't completed upload is ``PENDING``
          // server-side; letting that land on ``f.scanStatus`` here would
          // pin ``scanStatus="pending"`` on a row that only completes its
          // upload later, breaking the ``state==="done" &&
          // scanStatus===undefined`` guard that re-arms the poller on the
          // next transition to ``done``. Concurrent multi-uploads where a
          // later file is ``too_large`` would then never have their verdict
          // read at all. The client is authoritative for the upload phase;
          // the server's row-state serialization is only meaningful once
          // we've said ``state==="done"``.
          if (f.state !== "done") return f;
          if (
            server.scan_status === f.scanStatus &&
            server.scan_error_kind === (f.scanErrorKind ?? "") &&
            server.scan_submitted === f.scanSubmitted
          )
            return f;
          return {
            ...f,
            scanStatus: server.scan_status,
            scanErrorKind: server.scan_error_kind,
            scanSubmitted: server.scan_submitted,
          };
        });
        const mutated = next.some(
          (f, i) =>
            filesRef.current[i]?.scanStatus !== f.scanStatus ||
            filesRef.current[i]?.scanErrorKind !== f.scanErrorKind ||
            filesRef.current[i]?.scanSubmitted !== f.scanSubmitted,
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
    // ``scanSignal`` is the compressed scan-relevant slice of ``files`` — see
    // the useMemo above. Depending on it (and not on ``files``) means the
    // interval isn't torn down and re-armed on every chunk-progress update.
    // ``files`` itself is intentionally NOT listed: ``filesRef.current``
    // inside ``tick`` reads the fresh list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanSignal, writeFiles, scanTimedOut, isScanning]);

  // Re-arm scanning after the poller gave up. Re-submitting is the point: by
  // the time we time out, the backend's submit task has already exhausted its
  // retries and died, so merely resuming the poll would find nothing in flight.
  // Ask the server to re-queue the scan, then restart polling to pick up the
  // fresh verdict. Best-effort — a failed re-arm just leaves the retry visible.
  const retryScan = useCallback(async () => {
    const id = draftIdRef.current;
    // Reject overlapping retries: a second in-flight re-submit would race the
    // first and could momentarily null the deadline (see below).
    if (!id || isRetryingRef.current) return;
    isRetryingRef.current = true;
    setIsRetrying(true);
    try {
      await apiFetch(`/drafts/${id}/rescan/`, { method: "POST" });
    } catch {
      // Network/hiccup — keep the timed-out state so the user can retry again.
      return;
    } finally {
      isRetryingRef.current = false;
      setIsRetrying(false);
    }
    // Arm a *fresh* deadline rather than nulling it: if `setScanTimedOut(false)`
    // is a no-op (state already false), the poller effect won't re-run to
    // re-anchor a null deadline, and the next tick would read `now > null` and
    // time out immediately. A concrete deadline is always valid.
    scanDeadlineRef.current = Date.now() + SCAN_MAX_WAIT_MS;
    setScanTimedOut(false);
  }, []);

  const registerFile = useCallback(
    async (
      draftFile: DraftFile,
      knownDraftId: string | null,
    ): Promise<string | null> => {
      try {
        // Every transfer is encrypted, so ``size`` is always the post-
        // encryption size the backend's head_object check validates, and
        // ``plaintext_size`` tracks the pre-encryption size. The key is
        // generated on the first file (browser or Drive): browser files are
        // encrypted client-side with it, and a non-confidential Drive import
        // is encrypted server-side with the same key at finalize.
        if (!encryptionKeyRef.current) {
          const { cryptoKey, fragment } = await generateTransferKey();
          encryptionKeyRef.current = cryptoKey;
          keyFragmentRef.current = fragment;
          setKeyFragment(fragment);
        }
        const declaredSize = ciphertextSize(
          draftFile.size,
          chunkSizeFromConfig,
        );
        const resp = await apiFetch<AddFileResponse>(
          "/drafts/add-file/",
          {
            method: "POST",
            body: JSON.stringify({
              ...(knownDraftId ? { draft_id: knownDraftId } : {}),
              filename: draftFile.name,
              size: declaredSize,
              plaintext_size: draftFile.size,
              mime_type: draftFile.mimeType || "application/octet-stream",
              ...(draftFile.sourceUrl
                ? { source_url: draftFile.sourceUrl }
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

        // Drive-import path: no upload_id / s3_key / chunk_size echoed back.
        // The import is deferred to finalize (encrypted server-side there),
        // so the file is immediately ``done`` locally — ready to send. The
        // finalize 202 loop reports the actual import progress.
        if (draftFile.sourceUrl) {
          updateFile(draftFile.key, {
            backendId: resp.transfer_file_id,
            state: "done",
            loaded: draftFile.total,
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
    [updateFile, chunkSizeFromConfig],
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
        try {
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
        } catch (err) {
          // ``draftInitPromiseRef.current`` rejects ("Draft aborted during
          // initialization") or ``registerFile`` throws (network hiccup on
          // add-file, backend 4xx). Without this catch the ``void (async …)``
          // would leave an unhandled promise rejection and the file would
          // sit forever in ``registering``. Surface it on the row so the
          // user sees why and can retry / remove.
          updateFile(draftFile.key, {
            state: "error",
            error: err instanceof Error ? err.message : String(err),
          });
        }
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
        //
        // Confidentiality is decided here: for a non-confidential transfer we
        // post the key so the backend can serve it to recipients (and encrypt
        // Drive imports server-side). For a confidential transfer the key is
        // withheld — it never crosses the /finalize/ wire.
        //
        // Finalize is a 202 loop: it returns 202 while files are scanning or
        // Drive files are still importing, and 200 with the Transfer once
        // everything has landed. A 4xx (scan_blocked, drive_import_failed…)
        // is thrown by apiFetch and surfaced to the caller.
        const isConfidential = confidentialRef.current;
        const fragment = keyFragmentRef.current;
        // Non-confidential must ship the key. It's minted on the first file's
        // registration, so it's always here by now — guard anyway.
        if (!isConfidential && !fragment) {
          throw new Error("Encryption key not ready");
        }
        const finalizeBody = {
          ...metadata,
          confidential: isConfidential,
          ...(isConfidential ? {} : { encryption_key: fragment }),
        };
        // Deadlines are armed the first time each phase actually shows up in
        // the finalize response, not at submit() start. Setting them here
        // would make a slow Drive import eat into the scan window that
        // hasn't even started yet — a 40 min import followed by a 5 min
        // scan would trip the scan deadline immediately at the first
        // ``scan_pending`` because the clock had been running since submit.
        let scanDeadline: number | null = null;
        let driveDeadline: number | null = null;
        let driveInterval = DRIVE_IMPORT_POLL_INITIAL_MS;
        let finalized: TransferDetail;
        for (;;) {
          const resp = await apiFetch<TransferDetail | FinalizePendingResponse>(
            `/drafts/${id}/finalize/`,
            {
              method: "POST",
              body: JSON.stringify(finalizeBody),
            },
          );
          const reason = (resp as FinalizePendingResponse)?.reason;
          if (reason === "scan_pending" || reason === "drive_importing") {
            if (reason === "scan_pending") {
              if (scanDeadline === null) {
                scanDeadline = Date.now() + SCAN_MAX_WAIT_MS;
              }
            } else if (driveDeadline === null) {
              driveDeadline = Date.now() + DRIVE_IMPORT_MAX_WAIT_MS;
            }
            const deadline =
              reason === "scan_pending" ? scanDeadline : driveDeadline;
            if (Date.now() > (deadline as number)) {
              throw new Error("finalize_timeout");
            }
            let interval: number;
            if (reason === "scan_pending") {
              setIsScanning(true);
              setIsImportingDrive(false);
              setDriveImportProgress([]);
              // Reaching scan_pending means every Drive file finished
              // importing — the backend moved past _process_drive_imports.
              // The last ``bytes_imported`` we saw might have been 0 (task
              // hadn't bumped it before completing on a small file), so
              // fill in the final value here so the ring doesn't get stuck
              // at 0 % throughout the scan phase.
              // Also flip ``state`` to ``"done"`` here: the import phase is
              // over (backend moved past ``_process_drive_imports``), and
              // leaving the row at ``"importing"`` would keep it invisible
              // to the scan poller's ``state === "done"`` guard so the scan
              // verdict for a Drive-imported file would never surface on
              // its badge.
              writeFiles(
                filesRef.current.map((f) =>
                  f.sourceUrl && f.state === "importing"
                    ? { ...f, state: "done", loaded: f.total }
                    : f,
                ),
              );
              interval = SCAN_POLL_INTERVAL_MS;
            } else {
              setIsImportingDrive(true);
              setIsScanning(false);
              const progress =
                (resp as FinalizePendingResponse).import_progress ?? [];
              setDriveImportProgress(progress);
              // Feed ``loaded`` on each Drive draft file and flip its
              // state to ``"importing"`` so the same ``UploadRing`` +
              // ``file-item__pct`` that browser uploads use renders the
              // % on the file's row — consistent look with local uploads
              // instead of a separate list. Nothing else in the codebase
              // sets ``state = "importing"``, so this is where a Drive
              // file transitions from ``registered`` into the active
              // import phase.
              if (progress.length) {
                const byId = new Map(progress.map((p) => [p.file_id, p]));
                writeFiles(
                  filesRef.current.map((f) => {
                    const p = f.backendId ? byId.get(f.backendId) : undefined;
                    return p
                      ? { ...f, state: "importing", loaded: p.bytes_imported }
                      : f;
                  }),
                );
              }
              interval = driveInterval;
              driveInterval = Math.min(
                driveInterval * 2,
                DRIVE_IMPORT_POLL_MAX_MS,
              );
            }
            await new Promise((r) => setTimeout(r, interval));
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
        setIsImportingDrive(false);
        setDriveImportProgress([]);
        cancelSubmitRef.current = false;
      }
    },
    [queryClient, resetLocal, setAwaitingUploads],
  );

  const cancelSubmit = useCallback(() => {
    if (isAwaitingUploadsRef.current) {
      cancelSubmitRef.current = true;
    }
  }, []);

  return {
    draftId,
    files,
    isAwaitingUploads,
    isFinalizing,
    isScanning,
    scanTimedOut,
    retryScan,
    isRetrying,
    isImportingDrive,
    driveImportProgress,
    error,
    confidential,
    keyFragment,
    // Synchronous mirror of ``keyFragment`` for callers that need to snapshot
    // the value before ``submit()``'s resetLocal clears it — a render may not
    // have flushed between ``setKeyFragment`` and the click that fires submit,
    // so the state value on the returned object can still be null.
    keyFragmentRef,
    setConfidential,
    addFile,
    attachFromDrive,
    removeFile,
    submit,
    cancelSubmit,
    abort: abortDraft,
  };
}
