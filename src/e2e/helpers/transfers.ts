import { expect, type Page } from "@playwright/test";
import type { TestFile } from "./files";

export interface NewTransfer {
  files: TestFile[];
  title: string;
  mode: "link" | "email";
  recipients?: string[];
  confidential?: boolean;
  notifyOnDownload?: boolean;
  deactivateAfterDownload?: boolean;
}

export interface CreatedTransfer {
  id: string;
  // The share link, with the key fragment for a confidential transfer.
  link?: string;
  // The key shown apart from the link (confidential email mode).
  key?: string;
}

// Fill the new-transfer form on / and send it. Returns once the success
// screen shows.
export async function createTransfer(
  page: Page,
  transfer: NewTransfer,
): Promise<CreatedTransfer> {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Create a new transfer" }),
  ).toBeVisible();

  await page
    .locator('input[type="file"]')
    .setInputFiles(transfer.files.map((f) => f.path));
  await expect(
    page.getByRole("list", { name: "Selected files" }).getByRole("listitem"),
  ).toHaveCount(transfer.files.length);

  await page.getByLabel("Title").fill(transfer.title);

  if (transfer.mode === "link") {
    await page.getByRole("tab", { name: "Link" }).click();
  } else {
    const input = page.getByRole("textbox", { name: "Recipient email" });
    for (const email of transfer.recipients ?? []) {
      await input.fill(email);
      await input.press("Enter");
    }
  }

  const options = [
    transfer.confidential && "Confidential transfer",
    transfer.notifyOnDownload &&
      "Email me when a recipient downloads the files",
    transfer.deactivateAfterDownload &&
      "Deactivate after all files are downloaded",
  ].filter(Boolean) as string[];
  if (options.length) {
    await page.getByRole("button", { name: "Advanced options" }).click();
    for (const label of options) await page.getByLabel(label).check();
  }

  const submit =
    transfer.mode === "link"
      ? page.getByRole("button", { name: "Create link" })
      : page.getByRole("button", { name: /^Send \d+ files?$/ });
  await submit.click();

  await page.waitForURL(/\/confirm\/[0-9a-f-]+/);
  const id = new URL(page.url()).pathname.split("/").pop()!;

  if (transfer.mode === "link") {
    await expect(
      page.getByRole("heading", { name: "Transfer ready" }),
    ).toBeVisible();
    const link = await page.getByLabel("Download link").inputValue();
    return { id, link };
  }
  await expect(
    page.getByRole("heading", { name: "Transfer sent" }),
  ).toBeVisible({ timeout: 30_000 });
  const key = transfer.confidential
    ? await page.getByLabel("Decryption key").inputValue()
    : undefined;
  return { id, key };
}
