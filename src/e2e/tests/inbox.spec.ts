import { randomUUID } from "node:crypto";
import { expect, test, type Browser } from "@playwright/test";
import { anonymousPage, fillKeycloak } from "../helpers/auth";
import { deposit, newDepositor } from "../helpers/deposits";
import { makeFile, uniqueTitle, type TestFile } from "../helpers/files";
import { linkIn, waitForMail } from "../helpers/mail";
import { createUser } from "../helpers/keycloak";

// An anonymous send to ``recipient`` through /send. Returns the email the
// recipient receives.
async function sendTo(
  browser: Browser,
  recipient: string,
  title: string,
  files: TestFile[],
) {
  const depositor = newDepositor();
  const visitor = await anonymousPage(browser);
  await visitor.goto("/send");
  await expect(
    visitor.getByRole("heading", { name: "Send files to an agent" }),
  ).toBeVisible();
  await visitor.getByLabel("Recipient's email address").fill(recipient);
  await deposit(visitor, depositor, title, files);
  await visitor.context().close();
  return waitForMail({
    to: recipient,
    subject: new RegExp(`Nouveau dépôt de ${depositor.email}`),
  });
}

// An account changes where its address's sends go for good, so each test
// signs up Keycloak users of its own.
test("an agent collects an anonymous send, and later ones attach at once", async ({
  browser,
}, testInfo) => {
  const agent = await createUser("inbox");
  const title = uniqueTitle("Inbox send");
  const mail = await sendTo(browser, agent.email, title, [
    await makeFile(testInfo, "scan.pdf", 4_000),
  ]);
  const claimLink = linkIn(mail, "/inbox/claim?token=");

  // An account from another domain cannot collect it.
  const outsider = await createUser("outsider", "elsewhere.local");
  const other = await anonymousPage(browser);
  await other.goto(claimLink);
  await fillKeycloak(other, outsider);
  await expect(
    other.getByText(
      "These files were sent to another organization. Sign in with an account from that organization.",
    ),
  ).toBeVisible();
  await other.context().close();

  // The addressee, signed out, signs in on the way and lands on the send.
  const page = await anonymousPage(browser);
  await page.goto(claimLink);
  await fillKeycloak(page, agent);
  await page.waitForURL(/\/transfers\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Collected").first()).toBeVisible();

  // The next send to that address needs no claim.
  const nextTitle = uniqueTitle("Inbox send");
  const next = await sendTo(browser, agent.email, nextTitle, [
    await makeFile(testInfo, "scan-2.pdf", 4_000),
  ]);
  expect(next.text).not.toContain("/inbox/claim");
  await page.goto(linkIn(next, "/transfers/"));
  await expect(page.getByRole("heading", { name: nextTitle })).toBeVisible();

  // Both are in the inbox.
  await page.goto("/inbox");
  const inbox = page.locator(".deposits__list");
  await expect(inbox.getByRole("link", { name: new RegExp(title) })).toBeVisible();
  await expect(inbox.getByRole("link", { name: new RegExp(nextTitle) })).toBeVisible();
  await page.context().close();
});

test("the first colleague collects a send to a shared address", async ({
  browser,
}, testInfo) => {
  const shared = `contact-${randomUUID().slice(0, 8)}@example.local`;
  const title = uniqueTitle("Shared send");
  const mail = await sendTo(browser, shared, title, [
    await makeFile(testInfo, "scan.pdf", 4_000),
  ]);
  const claimLink = linkIn(mail, "/inbox/claim?token=");

  const first = await createUser("first");
  const page = await anonymousPage(browser);
  await page.goto(claimLink);
  await fillKeycloak(page, first);
  await page.waitForURL(/\/transfers\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.context().close();

  // The next colleague is told who to ask.
  const second = await createUser("second");
  const late = await anonymousPage(browser);
  await late.goto(claimLink);
  await fillKeycloak(late, second);
  await expect(
    late.getByText(`These files were already collected by ${first.email}.`),
  ).toBeVisible();
  await late.context().close();

  // The address still has no account, so the next send waits for a claim.
  const next = await sendTo(browser, shared, uniqueTitle("Shared send"), [
    await makeFile(testInfo, "scan-2.pdf", 4_000),
  ]);
  expect(next.text).toContain("/inbox/claim");
});

test("an address outside the instance pattern is refused", async ({ browser }) => {
  const visitor = await anonymousPage(browser);
  await visitor.goto("/send");
  const depositor = newDepositor();
  await visitor.getByLabel("Recipient's email address").fill("someone@example.org");
  await visitor.getByLabel("Your name").fill(depositor.name);
  await visitor.getByLabel("Your email address").fill(depositor.email);
  await visitor.getByRole("button", { name: "Receive a code" }).click();
  await expect(
    visitor.getByText("Files can't be sent to this address here."),
  ).toBeVisible();
  await visitor.context().close();
});
