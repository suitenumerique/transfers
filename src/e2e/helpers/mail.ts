import { expect } from "@playwright/test";
import { MAIL_URL } from "../playwright.config";

// Emails caught by maildev, read through its REST API.
export interface Mail {
  id: string;
  subject: string;
  text: string;
  html: string;
  date: string;
  to: { address: string; name?: string }[];
}

async function allMails(): Promise<Mail[]> {
  const response = await fetch(`${MAIL_URL}/email`);
  if (!response.ok) throw new Error(`maildev answered ${response.status}`);
  return (await response.json()) as Mail[];
}

interface MailQuery {
  to: string;
  // Matched against the subject.
  subject?: RegExp;
  // Matched against the plain-text body: tests run in parallel and share
  // the dev users' mailboxes, so a unique title in the body tells their
  // emails apart.
  body?: RegExp | string;
}

function matches(mail: Mail, query: MailQuery): boolean {
  const to = query.to.toLowerCase();
  if (!mail.to.some((r) => r.address.toLowerCase() === to)) return false;
  if (query.subject && !query.subject.test(mail.subject)) return false;
  if (query.body) {
    const found =
      typeof query.body === "string"
        ? mail.text.includes(query.body)
        : query.body.test(mail.text);
    if (!found) return false;
  }
  return true;
}

// The newest email matching ``query``, waiting for the worker to send it.
export async function waitForMail(query: MailQuery): Promise<Mail> {
  let found: Mail | undefined;
  await expect
    .poll(
      async () => {
        const mails = await allMails();
        found = mails
          .filter((m) => matches(m, query))
          .sort((a, b) => b.date.localeCompare(a.date))[0];
        return Boolean(found);
      },
      {
        message: `an email to ${query.to} matching ${query.subject ?? ""} ${query.body ?? ""}`,
        timeout: 30_000,
      },
    )
    .toBe(true);
  return found!;
}

// Every email matching ``query`` right now.
export async function findMails(query: MailQuery): Promise<Mail[]> {
  return (await allMails()).filter((m) => matches(m, query));
}

// The first link in the text body whose URL contains ``fragment``.
export function linkIn(mail: Mail, fragment: string): string {
  const links = mail.text.match(/https?:\/\/[^\s<>")]+/g) ?? [];
  const link = links.find((l) => l.includes(fragment));
  if (!link) {
    throw new Error(
      `No link containing "${fragment}" in "${mail.subject}":\n${mail.text}`,
    );
  }
  return link;
}
