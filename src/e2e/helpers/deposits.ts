import { randomUUID } from "node:crypto";
import { expect, type Page } from "@playwright/test";
import type { TestFile } from "./files";
import { waitForMail } from "./mail";

export interface Depositor {
  name: string;
  email: string;
}

// Someone without an account, with an address no other test uses.
export function newDepositor(): Depositor {
  const id = randomUUID().slice(0, 8);
  return { name: `Camille ${id}`, email: `depositor-${id}@example.org` };
}

// The one-time code mailed to ``email``: it is in the subject.
export async function depositCode(email: string): Promise<string> {
  const mail = await waitForMail({
    to: email,
    subject: /Votre code de vérification : \d{6}/,
  });
  return mail.subject.match(/(\d{6})/)![1];
}

// Steps 1 to 4 of the deposit wizard, on a page already showing step 1
// (/d/<token>, or /send with the recipient filled in).
export async function deposit(
  page: Page,
  depositor: Depositor,
  title: string,
  files: TestFile[],
) {
  await page.getByLabel("Your name").fill(depositor.name);
  await page.getByLabel("Your email address").fill(depositor.email);
  await page.getByLabel("Subject of your deposit").fill(title);
  await page.getByRole("button", { name: "Receive a code" }).click();

  await expect(
    page.getByText(`We sent a 6-digit code to ${depositor.email}.`),
  ).toBeVisible();
  await page.getByLabel("Code").fill(await depositCode(depositor.email));
  await page.getByRole("button", { name: "Check the code" }).click();

  await page.locator('input[type="file"]').setInputFiles(files.map((f) => f.path));
  await expect(
    page.getByRole("list", { name: "Selected files" }).getByRole("listitem"),
  ).toHaveCount(files.length);
  await page.getByRole("button", { name: "Send the files" }).click();

  await expect(
    page.getByRole("heading", { name: "Your files were sent" }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(
    page.getByText(`A confirmation was sent to ${depositor.email}.`),
  ).toBeVisible();
}
