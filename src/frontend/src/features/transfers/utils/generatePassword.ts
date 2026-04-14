import { getWordlist } from "./wordlists";

const DEFAULT_WORD_COUNT = 5;

export function generatePassphrase(
  locale: string | undefined,
  wordCount = DEFAULT_WORD_COUNT,
): string {
  const wordlist = getWordlist(locale);
  const buf = new Uint32Array(wordCount);
  crypto.getRandomValues(buf);
  const words: string[] = [];
  for (let i = 0; i < wordCount; i++) {
    words.push(wordlist[buf[i] % wordlist.length]);
  }
  return words.join("-");
}
