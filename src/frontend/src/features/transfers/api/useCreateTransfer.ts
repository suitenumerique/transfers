import { useCallback, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";
import { MultipartUploader } from "../upload/MultipartUploader";

// Flow:
//  1. POST /transfers/ — metadata only (title, filename, size, mime_type,
//     expires_in_days). Backend creates the Transfer row, initiates the S3
//     multipart upload, returns the upload_id + chunk_size.
//  2. MultipartUploader slices the file, asks /transfers/{id}/sign-part/ for
//     a presigned URL per chunk, PUTs each chunk directly to S3.
//  3. POST /transfers/{id}/complete-upload/ with the list of {PartNumber,
//     ETag}. Backend calls complete_multipart_upload on S3 and returns the
//     full TransferDetail.
//  4. If anything throws, POST /transfers/{id}/abort-upload/ to clean up.

interface CreateTransferInput {
  title: string;
  expires_in_days: number;
  file: File;
  password?: string;
}

interface InitiateResponse {
  transfer_id: string;
  transfer_file_id: string;
  upload_id: string;
  s3_key: string;
  chunk_size: number;
  public_token: string;
}

interface SignPartResponse {
  url: string;
  part_number: number;
}

export interface UploadHandle {
  abort: () => void;
}

export function useCreateTransfer(opts?: {
  onProgress?: (loaded: number, total: number) => void;
}) {
  const queryClient = useQueryClient();
  const uploaderRef = useRef<MultipartUploader | null>(null);

  const abort = useCallback(() => {
    uploaderRef.current?.abort();
  }, []);

  const mutation = useMutation({
    mutationFn: async (input: CreateTransferInput): Promise<TransferDetail> => {
      // Step 1 — initiate
      const initiate = await apiFetch<InitiateResponse>("/transfers/", {
        method: "POST",
        body: JSON.stringify({
          title: input.title,
          expires_in_days: input.expires_in_days,
          filename: input.file.name,
          size: input.file.size,
          mime_type: input.file.type || "application/octet-stream",
          ...(input.password ? { password: input.password } : {}),
        }),
      });

      // Step 2 — upload parts to S3 directly
      const uploader = new MultipartUploader({
        file: input.file,
        chunkSize: initiate.chunk_size,
        parallelism: 4,
        signPart: async (partNumber) => {
          const response = await apiFetch<SignPartResponse>(
            `/transfers/${initiate.transfer_id}/sign-part/`,
            {
              method: "POST",
              body: JSON.stringify({
                transfer_file_id: initiate.transfer_file_id,
                part_number: partNumber,
              }),
            },
          );
          return response.url;
        },
        onProgress: opts?.onProgress,
      });
      uploaderRef.current = uploader;

      let parts;
      try {
        parts = await uploader.upload();
      } catch (err) {
        // Best-effort cleanup: tell the backend to abort the S3 upload and
        // delete the partial rows. We swallow any error here because the
        // original upload error is what we want to surface.
        try {
          await apiFetch(
            `/transfers/${initiate.transfer_id}/abort-upload/`,
            {
              method: "POST",
              body: JSON.stringify({
                transfer_file_id: initiate.transfer_file_id,
              }),
            },
          );
        } catch {
          // ignore
        }
        throw err;
      } finally {
        uploaderRef.current = null;
      }

      // Step 3 — complete
      return apiFetch<TransferDetail>(
        `/transfers/${initiate.transfer_id}/complete-upload/`,
        {
          method: "POST",
          body: JSON.stringify({
            transfer_file_id: initiate.transfer_file_id,
            parts,
          }),
        },
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });

  return Object.assign(mutation, { abort });
}
