import { expect, test } from "@playwright/test";
import { anonymousPage, storageStateOf, USER1 } from "../helpers/auth";
import { downloadedBytes, makeFile, uniqueTitle } from "../helpers/files";
import { createTransfer } from "../helpers/transfers";

test.use({ storageState: storageStateOf(USER1) });

test("a link transfer is downloaded by anyone with the link", async ({
  page,
  browser,
}, testInfo) => {
  const files = [
    await makeFile(testInfo, "report.pdf", 150_000),
    await makeFile(testInfo, "photo.jpg", 3_000),
  ];
  const title = uniqueTitle("Link transfer");
  const { id, link } = await createTransfer(page, {
    files,
    title,
    mode: "link",
  });
  expect(link).toMatch(/^http:\/\/localhost:7980\/t\/[\w-]+$/);

  // A visitor without an account.
  const visitor = await anonymousPage(browser);
  await visitor.goto(link!);
  await expect(visitor.getByRole("heading", { name: title })).toBeVisible();
  await expect(
    visitor.getByRole("list", { name: "Files (2)" }).getByRole("listitem"),
  ).toHaveCount(2);

  // Decrypted in the browser by the service worker: same bytes as uploaded.
  for (const file of files) {
    const button = visitor.getByRole("button", {
      name: `Download ${file.name}`,
    });
    await expect(button).toBeEnabled();
    const [download] = await Promise.all([
      visitor.waitForEvent("download"),
      button.click(),
    ]);
    expect(download.suggestedFilename()).toBe(file.name);
    expect((await downloadedBytes(download)).equals(file.content)).toBe(true);
  }
  await visitor.context().close();

  // The owner sees the visit in the history.
  await page.goto(`/transfers/${id}`);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Link opened").first()).toBeVisible();
  await expect(page.getByText("File downloaded").first()).toBeVisible();
});

test("a deactivate-after-download link closes once every file is fetched", async ({
  page,
  browser,
}, testInfo) => {
  const file = await makeFile(testInfo, "once.txt", 500);
  const title = uniqueTitle("Single use");
  const { link } = await createTransfer(page, {
    files: [file],
    title,
    mode: "link",
    deactivateAfterDownload: true,
  });

  const visitor = await anonymousPage(browser);
  await visitor.goto(link!);
  await expect(
    visitor.getByText("Single-use link. Deactivates after full download."),
  ).toBeVisible();
  const [download] = await Promise.all([
    visitor.waitForEvent("download"),
    visitor.getByRole("button", { name: `Download ${file.name}` }).click(),
  ]);
  expect((await downloadedBytes(download)).equals(file.content)).toBe(true);

  // The next visitor finds it closed.
  await expect(async () => {
    const next = await anonymousPage(browser);
    await next.goto(link!);
    await expect(
      next.getByText("This link has been deactivated by the sender."),
    ).toBeVisible({ timeout: 3_000 });
    await next.context().close();
  }).toPass({ timeout: 30_000 });
});
