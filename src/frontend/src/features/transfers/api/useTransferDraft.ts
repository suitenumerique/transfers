import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { SharingMode, TransferDetail } from "@/features/api/types";
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
  | "registering" // POST /transfers or /add-file in flight
  | "registered" // waiting in queue for the upload pump
  | "uploading" // MultipartUploader is pushing chunks to S3
  | "done" // complete-upload succeeded
  | "error"; // registration or upload failed

export interface DraftFile {
  key: string;
  file: File;
  backendId: string | null;
  s3Key: string | null;
  uploadId: string | null;
  chunkSize: number | null;
  loaded: number;
  total: number;
  state: DraftFileState;
  error?: string;
}

export interface FinalizeMetadata {
  title?: string;
  expires_in_days?: number;
  sharing_mode?: SharingMode;
  recipients?: string[];
  sensitive?: boolean;
}

export interface TransferDraftHandle {
  draftId: string | null;
  files: DraftFile[];
  isSubmitting: boolean;
  error: string | null;
  addFile: (file: File) => void;
  removeFile: (key: string) => void;
  submit: (metadata: FinalizeMetadata) => Promise<TransferDetail>;
  abort: () => Promise<void>;
}

interface AddFileResponse {
  draft_id: string;
  transfer_file_id: string;
  upload_id: string;
  s3_key: string;
  chunk_size: number;
}

interface SignPartResponse {
  url: string;
  part_number: number;
}

export function fileKey(f: File): string {
  return `${f.name}|${f.size}|${f.lastModified}`;
}

const POLL_INTERVAL_MS = 200;

export function useTransferDraft(): TransferDraftHandle {
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState<string | null>(null);
  const [files, setFiles] = useState<DraftFile[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  }, [writeFiles]);

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
  // pick the first `registered` file and start it.
  useEffect(() => {
    if (currentUploaderRef.current) return;
    const next = files.find((f) => f.state === "registered");
    if (!next || !next.backendId || !next.chunkSize) return;

    const backendId = next.backendId;
    const chunkSize = next.chunkSize;
    const key = next.key;

    const uploader = new MultipartUploader({
      file: next.file,
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
        updateFile(key, { state: "done", loaded: next.file.size });
      })
      .catch((err) => {
        // Don't leak an error state if the user explicitly aborted the whole
        // draft — the local row is already gone.
        if (!filesRef.current.some((f) => f.key === key)) return;
        updateFile(key, { state: "error", error: String(err) });
        setError(String(err));
        // All-or-nothing: a single file failure tears down the whole draft,
        // matching the server-side semantics of complete_upload on bad ETag.
        void abortDraft();
      })
      .finally(() => {
        currentUploaderRef.current = null;
      });
  }, [files, abortDraft, updateFile]);

  const registerFile = useCallback(
    async (
      draftFile: DraftFile,
      knownDraftId: string | null,
    ): Promise<string | null> => {
      try {
        const resp = await apiFetch<AddFileResponse>(
          "/drafts/add-file/",
          {
            method: "POST",
            body: JSON.stringify({
              ...(knownDraftId ? { draft_id: knownDraftId } : {}),
              filename: draftFile.file.name,
              size: draftFile.file.size,
              mime_type:
                draftFile.file.type || "application/octet-stream",
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

        updateFile(draftFile.key, {
          backendId: resp.transfer_file_id,
          uploadId: resp.upload_id,
          s3Key: resp.s3_key,
          chunkSize: resp.chunk_size,
          state: "registered",
        });
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

  const addFile = useCallback(
    (file: File) => {
      const key = fileKey(file);
      // Guard against duplicate drops sneaking past the caller's dedupe.
      if (filesRef.current.some((f) => f.key === key)) return;

      const draftFile: DraftFile = {
        key,
        file,
        backendId: null,
        s3Key: null,
        uploadId: null,
        chunkSize: null,
        loaded: 0,
        total: file.size,
        state: "registering",
      };
      writeFiles([...filesRef.current, draftFile]);
      setError(null);

      if (
        draftIdRef.current === null &&
        draftInitPromiseRef.current === null
      ) {
        // First drop: this call will birth the draft on the backend. Store
        // the promise so concurrent addFile calls wait for the draft id
        // instead of racing multiple "create-draft" requests.
        draftInitPromiseRef.current = registerFile(draftFile, null).then(
          (id) => {
            if (!id) {
              throw new Error("Draft aborted during initialization");
            }
            return id;
          },
        );
        // Swallow the rejection at this top-level call site — the error
        // state on the file row carries enough info for the UI.
        draftInitPromiseRef.current.catch(() => {});
        return;
      }

      // Not the first drop: wait for the draft id (may already be resolved)
      // then attach the file to it.
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

  const removeFile = useCallback(
    async (key: string) => {
      const target = filesRef.current.find((f) => f.key === key);
      if (!target) return;

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

      setIsSubmitting(true);
      try {
        // Wait for every file to reach "done". Polling ref state is fine —
        // the UI already shows per-file progress, and the wait is bounded
        // by the last byte landing in S3.
        await new Promise<void>((resolve, reject) => {
          const tick = () => {
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

        // Metadata is frozen here — the draft held nothing but files, and
        // finalize is the one write that creates the Transfer with its
        // title / sharing mode / recipients / expiry / sensitive in a
        // single atomic step. The returned Transfer has a *different* id
        // from the draft.
        const finalized = await apiFetch<TransferDetail>(
          `/drafts/${id}/finalize/`,
          {
            method: "POST",
            body: JSON.stringify(metadata),
          },
        );

        queryClient.invalidateQueries({ queryKey: ["transfers"] });
        resetLocal();
        return finalized;
      } finally {
        setIsSubmitting(false);
      }
    },
    [queryClient, resetLocal],
  );

  return {
    draftId,
    files,
    isSubmitting,
    error,
    addFile,
    removeFile,
    submit,
    abort: abortDraft,
  };
}
