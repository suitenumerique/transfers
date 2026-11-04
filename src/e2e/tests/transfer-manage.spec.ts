import { expect, test } from "@playwright/test";
import { anonymousPage, pageAs, storageStateOf, USER1, USER2 } from "../helpers/auth";
import { makeFile, uniqueTitle } from "../helpers/files";
import { createTransfer } from "../helpers/transfers";

test.use({ storageState: storageStateOf(USER1) });

test("an agent finds, deactivates and deletes a transfer", async ({
  page,
  browser,
}, testInfo) => {
  const file = await makeFile(testInfo, "manage.txt", 300);
  const title = uniqueTitle("Manage");
  const { id, link } = await createTransfer(page, {
    files: [file],
    title,
    mode: "link",
  });
  await page.getByRole("button", { name: "View summary" }).click();
  await expect(page).toHaveURL(new RegExp(`/transfers/${id}$`));

  // The sidebar search finds it by its title.
  await page
    .getByRole("searchbox", { name: "Search transfers" })
    .fill(title.split(" ")[1]);
  await expect(page.getByRole("link", { name: title })).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();

  // Deactivate: the link stops working at once.
  await page.getByRole("button", { name: "Deactivate", exact: true }).click();
  const confirm = page.getByRole("dialog");
  await expect(confirm.getByText("Confirm deactivation")).toBeVisible();
  await confirm.getByRole("button", { name: "Deactivate" }).click();
  await expect(page.getByText("Deactivated by you")).toBeVisible();
  await expect(page.getByText("Transfer deactivated").first()).toBeVisible();

  const visitor = await anonymousPage(browser);
  await visitor.goto(link!);
  await expect(
    visitor.getByText("This link has been deactivated by the sender."),
  ).toBeVisible();

  // Delete for good: back to the home page, and the link is unknown.
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete permanently" })
    .click();
  await expect(page).toHaveURL(/localhost:7980\/$/);
  await expect(page.getByRole("link", { name: title })).toHaveCount(0);

  await visitor.reload();
  await expect(visitor.getByText("This link does not exist.")).toBeVisible();
  await visitor.context().close();
});

test("another agent cannot open someone else's transfer", async ({
  page,
  browser,
}, testInfo) => {
  const file = await makeFile(testInfo, "private.txt", 100);
  const { id } = await createTransfer(page, {
    files: [file],
    title: uniqueTitle("Private"),
    mode: "link",
  });
  const other = await pageAs(browser, USER2);
  await other.goto(`/transfers/${id}`);
  await expect(other.getByText("Transfer not found.")).toBeVisible();
  await other.context().close();
});
