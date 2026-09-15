import { beforeAll, describe, expect, it } from "vitest";
import i18n from "i18next";
import { ApiError } from "@/features/api/client";
import { UploadPartError } from "@/features/transfers/upload/uploadPart";
import { isNetworkError, userFacingError } from "./index";

beforeAll(async () => {
  // Bare instance: t() echoes the key, which is the English source string.
  if (!i18n.isInitialized) await i18n.init({ lng: "en", resources: {} });
});

describe("userFacingError", () => {
  it("maps a fetch that never reached the server to a connection message", () => {
    for (const msg of [
      "Failed to fetch",
      "NetworkError when attempting to fetch resource.",
      "Load failed",
    ]) {
      const err = new TypeError(msg);
      expect(isNetworkError(err)).toBe(true);
      expect(userFacingError(err)).toBe(
        "Can't reach the server. Check your connection and try again.",
      );
    }
  });

  it("treats a part upload network failure the same way", () => {
    const err = new UploadPartError("Network error during part upload");
    expect(isNetworkError(err)).toBe(true);
    expect(userFacingError(err)).toMatch(/Can't reach the server/);
  });

  it("passes a 4xx detail through and hides 5xx internals", () => {
    expect(userFacingError(new ApiError("File too large.", 400, {}))).toBe(
      "File too large.",
    );
    expect(userFacingError(new ApiError("Internal Server Error", 500, {}))).toBe(
      "The server ran into an error. Try again in a moment.",
    );
  });

  it("never shows an exception's toString()", () => {
    expect(userFacingError(new Error("boom"))).toBe("Something went wrong. Try again.");
    expect(userFacingError("boom")).toBe("Something went wrong. Try again.");
    expect(userFacingError(new UploadPartError("S3 part upload failed with HTTP 403", 403))).toBe(
      "The upload failed. Remove the file and add it again.",
    );
  });
});
