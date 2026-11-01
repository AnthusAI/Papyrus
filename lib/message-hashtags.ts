/** The hashtags a person typed in a Message body, lower-cased and in order of first appearance, without the leading "#". */
const HASHTAG_PATTERN = /(^|[^\w&/#-])#([A-Za-z0-9][A-Za-z0-9_-]*)/g;

export function hashtagsInMessageText(text: string | null | undefined): string[] {
  const found: string[] = [];
  if (!text) return found;
  for (const match of text.matchAll(HASHTAG_PATTERN)) {
    const name = match[2].replace(/[-_]+$/, "").toLowerCase();
    if (name && !found.includes(name)) found.push(name);
  }
  return found;
}
