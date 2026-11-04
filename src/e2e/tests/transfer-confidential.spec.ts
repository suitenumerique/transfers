import { expect, test } from "@playwright/test";
import { anonymousPage, storageStateOf, USER1 } from "../helpers/auth";
import { downloadedBytes, makeFile, uniqueTitle } from "../helpers/files";
import { linkIn, waitForMail } from "../helpers/mail";
import { createTransfer } from "../helpers/transfers";

test.use({ storageState: storageStateOf(USER1) });

test("a confidential link carries its key in the fragment", async ({
  page,
  browser,
}, testInfo) => {
  const file = await makeFile(testInfo, "secret.bin", 40_000);
  const title = uniqueTitle("Confidential link");
  const { id, link } = await createTransfer(page, {
    files: [file],
    title,
    mode: "link",
    confidential: true,
  });
  // The key never reaches the server: it only lives after the #.
  const [bareLink, key] = link!.split("#");
  expect(key).toMatch(/^[\w-]{43}$/);

  const visitor = await anonymousPage(browser);
  await visitor.goto(link!);
  await expect(visitor.getByRole("heading", { name: title })).toBeVisible();
  const [download] = await Promise.all([
    visitor.waitForEvent("download"),
    visitor.getByRole("button", { name: `Download ${file.name}` }).click(),
  ]);
  expect((await downloadedBytes(download)).equals(file.content)).toBe(true);
  await visitor.context().close();

  // Without the fragment, the files stay locked until the key is given.
  const other = await anonymousPage(browser);
  await other.goto(bareLink);
  await expect(
    other.getByText(
      "This transfer is confidential. Enter the decryption key the sender shared with you separately to unlock the files.",
    ),
  ).toBeVisible();
  // A malformed key is refused at once. (A well-formed wrong key only fails
  // when the files are decrypted, by design.)
  await other.getByLabel("Decryption key").fill("not-a-key");
  await other.getByRole("button", { name: "Unlock" }).click();
  await expect(
    other.getByText("That key didn't work. Check it and try again."),
  ).toBeVisible();
  await other.getByLabel("Decryption key").fill(key);
  await other.getByRole("button", { name: "Unlock" }).click();
  const [unlocked] = await Promise.all([
    other.waitForEvent("download"),
    other.getByRole("button", { name: `Download ${file.name}` }).click(),
  ]);
  expect((await downloadedBytes(unlocked)).equals(file.content)).toBe(true);
  await other.context().close();

  // The owner cannot rebuild the link: no key, no link box.
  await page.goto(`/transfers/${id}`);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Confidential").first()).toBeVisible();
  await expect(page.getByLabel("Download link")).toHaveCount(0);
});

test("a confidential email keeps the key out of the invitation", async ({
  page,
  browser,
}, testInfo) => {
  const file = await makeFile(testInfo, "secret-mail.bin", 5_000);
  const title = uniqueTitle("Confidential email");
  const recipient = "user3@example.local";
  const { key } = await createTransfer(page, {
    files: [file],
    title,
    mode: "email",
    recipients: [recipient],
    confidential: true,
  });
  expect(key).toMatch(/^[\w-]{43}$/);

  const invitation = await waitForMail({ to: recipient, body: title });
  expect(invitation.text).not.toContain(key!);
  expect(invitation.html).not.toContain(key!);

  const visitor = await anonymousPage(browser);
  await visitor.goto(linkIn(invitation, "/t/"));
  await visitor.getByLabel("Decryption key").fill(key!);
  await visitor.getByRole("button", { name: "Unlock" }).click();
  const [download] = await Promise.all([
    visitor.waitForEvent("download"),
    visitor.getByRole("button", { name: `Download ${file.name}` }).click(),
  ]);
  expect((await downloadedBytes(download)).equals(file.content)).toBe(true);
  await visitor.context().close();
});
