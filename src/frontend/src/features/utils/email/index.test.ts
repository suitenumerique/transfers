import { describe, expect, it } from "vitest";
import { inboxRecipientAllowed, isValidEmail } from ".";

describe("isValidEmail", () => {
  it("wants a dot and a TLD of two letters or more", () => {
    expect(isValidEmail("a@b.fr")).toBe(true);
    expect(isValidEmail(" a@b.fr ")).toBe(true);
    expect(isValidEmail("a@b")).toBe(false);
    expect(isValidEmail("a@b.c")).toBe(false);
  });
});

describe("inboxRecipientAllowed", () => {
  const pattern = "[^@]+@example\\.local";

  it("matches the whole address, any case", () => {
    expect(inboxRecipientAllowed(pattern, "Agent@Example.local")).toBe(true);
    expect(inboxRecipientAllowed(pattern, "a@example.local.evil.fr")).toBe(
      false,
    );
    expect(inboxRecipientAllowed(pattern, "a@other.fr")).toBe(false);
  });

  it("lets the address through without a pattern JS can read", () => {
    expect(inboxRecipientAllowed("", "a@other.fr")).toBe(true);
    expect(inboxRecipientAllowed("(?P<u>[^@]+)@x\\.fr", "a@other.fr")).toBe(
      true,
    );
  });
});
