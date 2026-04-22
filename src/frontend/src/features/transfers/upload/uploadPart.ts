// PUT a file blob (a multipart chunk) to a presigned S3 URL via XHR.
//
// Uses XHR instead of fetch() so we get per-request upload progress events,
// which are not exposed by the fetch API. Returns the ETag header from S3,
// which the caller will later pass to the completeMultipartUpload endpoint.
//
// Adapted from suitenumerique/drive's `StandardDriver.uploadFile()`.

export interface UploadPartOptions {
  url: string;
  blob: Blob;
  signal?: AbortSignal;
  onProgress?: (loaded: number) => void;
}

export interface UploadPartResult {
  etag: string;
}

export class UploadPartError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "UploadPartError";
  }
}

export function uploadPart({
  url,
  blob,
  signal,
  onProgress,
}: UploadPartOptions): Promise<UploadPartResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);

    // Bridge the caller's AbortSignal to xhr.abort() *and* clean the
    // listener up the moment this part's XHR finishes. Without explicit
    // removal the abort listener accumulates on the shared signal for
    // every part of the upload and keeps each XHR (and its 25 MiB blob
    // reference) alive — a 760-part / 19 GB upload was pinning tens of
    // gigabytes of RAM until we started removing the listener on load.
    const onAbort = () => xhr.abort();
    const cleanup = () => {
      if (signal) signal.removeEventListener("abort", onAbort);
    };

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(event.loaded);
      }
    });

    xhr.addEventListener("load", () => {
      cleanup();
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(
          new UploadPartError(
            `S3 part upload failed with HTTP ${xhr.status}`,
            xhr.status,
          ),
        );
        return;
      }
      // S3 returns the part's ETag (quoted string) in the ETag response
      // header. We keep the quotes because complete_multipart_upload expects
      // the exact ETag as returned.
      const etag = xhr.getResponseHeader("ETag");
      if (!etag) {
        reject(new UploadPartError("S3 part upload missing ETag header"));
        return;
      }
      resolve({ etag });
    });

    xhr.addEventListener("error", () => {
      cleanup();
      reject(new UploadPartError("Network error during part upload"));
    });

    xhr.addEventListener("abort", () => {
      cleanup();
      reject(new UploadPartError("Part upload aborted"));
    });

    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        return;
      }
      signal.addEventListener("abort", onAbort);
    }

    xhr.send(blob);
  });
}
