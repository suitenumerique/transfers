import { expect, test } from "@playwright/test";
import { anonymousPage, storageStateOf, USER1 } from "../helpers/auth";
import { downloadedBytes, makeFile, uniqueTitle } from "../helpers/files";
import { linkIn, waitForMail } from "../helpers/mail";
import { createTransfer } from "../helpers/transfers";

test.use({ storageState: storageStateOf(USER1) });

test("recipients get an invitation, and the sender a download receipt", async ({
  page,
  browser,
}, testInfo) => {
  const files = [
    await makeFile(testInfo, "a.txt", 1_000),
    await makeFile(testInfo, "b.txt", 2_000),
  ];
  const title = uniqueTitle("Email transfer");
  const recipients = ["user2@example.local", "user3@example.local"];
  const { id } = await createTransfer(page, {
    files,
    title,
    mode: "email",
    recipients,
    notifyOnDownload: true,
  });
  // Every recipient is listed with its delivery status.
  for (const email of recipients) {
    await expect(page.getByText(`<${email}>`).or(page.getByText(email)).first()).toBeVisible();
  }

  // Each recipient gets a personal link, without the key.
  const invitation = await waitForMail({ to: recipients[0], body: title });
  expect(invitation.subject).toContain("vous a envoyé des fichiers");
  const link = linkIn(invitation, "/t/");
  expect(link).toMatch(/\/t\/[\w-]+\?r=[\w-]+$/);
  await waitForMail({ to: recipients[1], body: title });

  const visitor = await anonymousPage(browser);
  await visitor.goto(link);
  await expect(visitor.getByRole("heading", { name: title })).toBeVisible();
  for (const file of files) {
    const [download] = await Promise.all([
      visitor.waitForEvent("download"),
      visitor.getByRole("button", { name: `Download ${file.name}` }).click(),
    ]);
    expect((await downloadedBytes(download)).equals(file.content)).toBe(true);
  }
  await visitor.context().close();

  // Every file fetched: the sender is told at once.
  const receipt = await waitForMail({
    to: "user1@example.local",
    subject: new RegExp(`^${recipients[0]} a téléchargé`),
    body: title,
  });
  expect(linkIn(receipt, "/transfers/")).toContain(id);

  // The detail page names the recipient in the history.
  await page.goto(`/transfers/${id}`);
  await expect(page.getByRole("button", { name: "Recipients (2)" })).toBeVisible();
  await expect(page.getByText("Notification email sent").first()).toBeVisible();
  await expect(
    page.locator(".transfer-detail__history-row", { hasText: "File downloaded" }).first(),
  ).toContainText(recipients[0]);
});

test("a bad recipient address is refused before sending", async ({ page }, testInfo) => {
  const file = await makeFile(testInfo, "c.txt", 100);
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(file.path);
  const input = page.getByRole("textbox", { name: "Recipient email" });
  await input.fill("not-an-address");
  await input.press("Enter");
  await expect(page.getByText("Invalid email address.")).toBeVisible();

  await input.fill("user2@example.local");
  await input.press("Enter");
  await input.fill("user2@example.local");
  await input.press("Enter");
  await expect(
    page.getByText("This recipient has already been added."),
  ).toBeVisible();
});
