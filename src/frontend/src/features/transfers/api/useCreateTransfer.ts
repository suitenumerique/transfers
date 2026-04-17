import { useCallback, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { SharingMode, TransferDetail } from "@/features/api/types";
import { MultipartUploader } from "../upload/MultipartUploader";

// Flow:
//  1. POST /transfers/ — sends transfer-level metadata + files array in one
//     call. Backend creates the Transfer (no public_token yet), creates all
//     TransferFiles, and initiates one S3 multipart upload per file, in a
//     single transaction. Returns the transfer id + chunk size + a parallel
//     array of per-file upload descriptors.
//  2. For each file sequentially:
//     2a. Instantiate a MultipartUploader that slices the file and pushes
//         its chunks to S3 directly via presigned URLs obtained from
//         /transfers/{id}/sign-part/
//     2b. POST /transfers/{id}/complete-upload/ with the {PartNumber, ETag}
//         list.
//  3. POST /transfers/{id}/finalize/ — atomic transition that generates the
//     public_token, sets upload_completed_at, emits TRANSFER_CREATED, and
//     returns the finalized transfer detail.
//  4. On any error mid-flow: POST /transfers/{id}/abort-upload/ on the
//     transfer — backend aborts every pending multipart upload and drops
//     the whole transfer (all-or-nothing semantics).

interface CreateTransferInput {
  title: string;
  expires_in_days: number;
  files: File[];
  sharing_mode?: SharingMode;
  recipients?: string[];
}

interface CreateFileDescriptor {
  transfer_file_id: string;
  upload_id: string;
  s3_key: string;
}

interface CreateResponse {
  transfer_id: string;
  chunk_size: number;
  files: CreateFileDescriptor[];
}

interface SignPartResponse {
  url: string;
  part_number: number;
}

export interface AggregateProgress {
  fileIndex: number;
  fileCount: number;
  fileName: string;
  fileLoaded: number;
  fileTotal: number;
  totalLoaded: number;
  totalTotal: number;
}

export function useCreateTransfer(opts?: {
  onProgress?: (progress: AggregateProgress) => void;
}) {
  const queryClient = useQueryClient();
  const uploaderRef = useRef<MultipartUploader | null>(null);

  const abort = useCallback(() => {
    uploaderRef.current?.abort();
  }, []);

  const mutation = useMutation({
    mutationFn: async (input: CreateTransferInput): Promise<TransferDetail> => {
      if (input.files.length === 0) {
        throw new Error("No file selected");
      }

      // Step 1 — create the transfer and initiate multipart uploads for
      // every file in one call.
      const created = await apiFetch<CreateResponse>("/transfers/", {
        method: "POST",
        body: JSON.stringify({
          title: input.title,
          expires_in_days: input.expires_in_days,
          sharing_mode: input.sharing_mode ?? "link",
          ...(input.recipients?.length ? { recipients: input.recipients } : {}),
          files: input.files.map((f) => ({
            filename: f.name,
            size: f.size,
            mime_type: f.type || "application/octet-stream",
          })),
        }),
      });

      const totalTotal = input.files.reduce((acc, f) => acc + f.size, 0);
      const priorLoadedByIndex: number[] = new Array(input.files.length).fill(0);

      const abortTransfer = async () => {
        try {
          await apiFetch(
            `/transfers/${created.transfer_id}/abort-upload/`,
            { method: "POST" },
          );
        } catch {
          // best-effort
        }
      };

      try {
        // Step 2 — upload each file's chunks sequentially. Within a file the
        // MultipartUploader parallelises chunks internally.
        for (let i = 0; i < input.files.length; i++) {
          const file = input.files[i];
          const descriptor = created.files[i];

          const uploader = new MultipartUploader({
            file,
            chunkSize: created.chunk_size,
            parallelism: 4,
            signPart: async (partNumber) => {
              const response = await apiFetch<SignPartResponse>(
                `/transfers/${created.transfer_id}/sign-part/`,
                {
                  method: "POST",
                  body: JSON.stringify({
                    transfer_file_id: descriptor.transfer_file_id,
                    part_number: partNumber,
                  }),
                },
              );
              return response.url;
            },
            onProgress: (loaded, total) => {
              priorLoadedByIndex[i] = loaded;
              const totalLoaded = priorLoadedByIndex.reduce((a, b) => a + b, 0);
              opts?.onProgress?.({
                fileIndex: i,
                fileCount: input.files.length,
                fileName: file.name,
                fileLoaded: loaded,
                fileTotal: total,
                totalLoaded,
                totalTotal,
              });
            },
          });
          uploaderRef.current = uploader;

          let parts;
          try {
            parts = await uploader.upload();
          } finally {
            uploaderRef.current = null;
          }

          priorLoadedByIndex[i] = file.size;
          await apiFetch(
            `/transfers/${created.transfer_id}/complete-upload/`,
            {
              method: "POST",
              body: JSON.stringify({
                transfer_file_id: descriptor.transfer_file_id,
                parts,
              }),
            },
          );
        }
      } catch (err) {
        await abortTransfer();
        throw err;
      }

      // Step 3 — finalize the transfer. This generates the public token,
      // marks the transfer as complete, and returns the full detail.
      const finalized = await apiFetch<TransferDetail>(
        `/transfers/${created.transfer_id}/finalize/`,
        { method: "POST" },
      );

      return finalized;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });

  return Object.assign(mutation, { abort });
}
