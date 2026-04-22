// Orchestrates a client-side S3 multipart upload for a single file.
//
// Responsibilities:
//  1. Slice the file into fixed-size chunks.
//  2. For each chunk, request a presigned URL from the backend (sign-part).
//  3. Upload the chunk to S3 via `uploadPart`.
//  4. Retry failed parts with exponential backoff (up to MAX_ATTEMPTS).
//  5. Limit parallelism to `parallelism` in-flight parts.
//  6. Report aggregate progress to the caller.
//  7. Return the list of {PartNumber, ETag} for the caller to pass to
//     completeMultipartUpload.
//
// The uploader does NOT know about the Transfer domain — it only needs a
// `signPart` function that takes a part number and returns a URL. The caller
// (useTransferDraft) wires that to the backend sign-part endpoint.

import { uploadPart } from "./uploadPart";

export interface UploadedPart {
  PartNumber: number;
  ETag: string;
}

export interface MultipartUploaderOptions {
  file: File;
  chunkSize: number;
  parallelism: number;
  // Ask the backend for a presigned URL to upload a specific part.
  signPart: (partNumber: number) => Promise<string>;
  // Aggregate progress callback. `loaded` and `total` are in bytes.
  onProgress?: (loaded: number, total: number) => void;
}

const MAX_ATTEMPTS = 5;
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

export class MultipartUploader {
  private readonly opts: MultipartUploaderOptions;
  private readonly totalParts: number;
  private readonly partProgress: number[];
  private abortController: AbortController;

  constructor(opts: MultipartUploaderOptions) {
    this.opts = opts;
    this.totalParts = Math.max(1, Math.ceil(opts.file.size / opts.chunkSize));
    this.partProgress = new Array(this.totalParts).fill(0);
    this.abortController = new AbortController();
  }

  /** Cancel all in-flight and pending uploads. */
  abort(): void {
    this.abortController.abort();
  }

  async upload(): Promise<UploadedPart[]> {
    const partNumbers = Array.from(
      { length: this.totalParts },
      (_, i) => i + 1,
    );
    const uploaded: UploadedPart[] = [];
    let nextIndex = 0;

    const worker = async () => {
      while (true) {
        if (this.abortController.signal.aborted) return;
        const index = nextIndex++;
        if (index >= partNumbers.length) return;
        const partNumber = partNumbers[index];
        const result = await this.uploadWithRetry(partNumber);
        uploaded.push(result);
      }
    };

    const workers = Array.from(
      { length: Math.min(this.opts.parallelism, this.totalParts) },
      () => worker(),
    );
    await Promise.all(workers);

    // Sort by PartNumber so the caller can send the list in order.
    uploaded.sort((a, b) => a.PartNumber - b.PartNumber);
    return uploaded;
  }

  private getBlob(partNumber: number): Blob {
    const start = (partNumber - 1) * this.opts.chunkSize;
    const end = Math.min(start + this.opts.chunkSize, this.opts.file.size);
    // Explicit binary type prevents Firefox from routing the blob through
    // its text-body path in XHR — on Fx 140+ an untyped slice was being
    // widened to a UTF-16 string per chunk (two-byte per byte, 252 live
    // copies observed in about:memory on a 19 GB upload = 15 GB of
    // string heap). application/octet-stream keeps it on the binary
    // stream path and the retention drops to blob refs only.
    return this.opts.file.slice(start, end, "application/octet-stream");
  }

  private async uploadWithRetry(partNumber: number): Promise<UploadedPart> {
    let lastError: unknown;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      if (this.abortController.signal.aborted) {
        throw new Error("Upload aborted");
      }
      try {
        const url = await this.opts.signPart(partNumber);
        const blob = this.getBlob(partNumber);
        // Reset progress for this part on retry — we don't double-count.
        this.partProgress[partNumber - 1] = 0;
        const { etag } = await uploadPart({
          url,
          blob,
          signal: this.abortController.signal,
          onProgress: (loaded) => {
            this.partProgress[partNumber - 1] = loaded;
            this.reportProgress();
          },
        });
        this.partProgress[partNumber - 1] = blob.size;
        this.reportProgress();
        return { PartNumber: partNumber, ETag: etag };
      } catch (err) {
        lastError = err;
        if (this.abortController.signal.aborted) {
          throw err;
        }
        if (attempt < MAX_ATTEMPTS - 1) {
          await sleep(BACKOFF_MS[attempt]);
        }
      }
    }
    throw lastError ?? new Error("Unknown upload error");
  }

  private progressFlushTimer: ReturnType<typeof setTimeout> | null = null;
  private lastProgressEmit = 0;

  // Throttle progress updates to ~10 Hz: XHR fires progress events many
  // times per second per chunk × 4 concurrent workers ⇒ without
  // throttling each byte round-trips through React re-renders, which
  // burns CPU (and thrashes GC) on large files. The trailing flush
  // guarantees the UI lands on the final 100 % value.
  private reportProgress(): void {
    if (!this.opts.onProgress) return;
    const now = performance.now();
    const elapsed = now - this.lastProgressEmit;
    if (elapsed >= 100) {
      this.flushProgress(now);
      return;
    }
    if (this.progressFlushTimer == null) {
      this.progressFlushTimer = setTimeout(
        () => this.flushProgress(performance.now()),
        100 - elapsed,
      );
    }
  }

  private flushProgress(now: number): void {
    if (this.progressFlushTimer != null) {
      clearTimeout(this.progressFlushTimer);
      this.progressFlushTimer = null;
    }
    this.lastProgressEmit = now;
    if (!this.opts.onProgress) return;
    const loaded = this.partProgress.reduce((acc, p) => acc + p, 0);
    this.opts.onProgress(loaded, this.opts.file.size);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
