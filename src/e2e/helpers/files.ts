import { randomBytes, randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import type { Download, TestInfo } from "@playwright/test";

export interface TestFile {
  name: string;
  path: string;
  content: Buffer;
}

// A file of random bytes in the test's output folder, so a download can be
// compared with what was uploaded.
export async function makeFile(
  testInfo: TestInfo,
  name: string,
  size = 2048,
): Promise<TestFile> {
  const content = randomBytes(size);
  const path = testInfo.outputPath(name);
  await writeFile(path, content);
  return { name, path, content };
}

export async function downloadedBytes(download: Download): Promise<Buffer> {
  const path = await download.path();
  return readFile(path);
}

// A title no other test (or earlier run) uses: emails and sidebar rows are
// found by it.
export function uniqueTitle(prefix: string): string {
  return `${prefix} ${randomUUID().slice(0, 8)}`;
}
