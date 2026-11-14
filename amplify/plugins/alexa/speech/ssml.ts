/**
 * SSML building blocks. Everything spoken goes through `escapeSsml`, and a spoken body is a list of units that is cut only at a
 * unit boundary (a sentence, a heading or a pause), so the response always stays under Alexa's output-speech limit.
 */

/** Alexa rejects output speech longer than 8000 characters (the whole SSML string, tags included). */
export const MAX_SSML_LENGTH = 8000;

// Characters XML 1.0 cannot carry at all (control characters other than tab, newline and carriage return).
const XML_ILLEGAL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g;

export function escapeSsml(text: string): string {
  return text
    .replace(XML_ILLEGAL, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

export function pause(milliseconds: number): string {
  return `<break time="${milliseconds}ms"/>`;
}

/** One sentence as SSML (already escaped). */
/** One spoken sentence. The trailing space keeps the on-screen caption from running sentences together ("budget.People"). */
export function sentence(text: string): string {
  return `<s>${escapeSsml(text)}</s> `;
}

export function wrapSpeak(inner: string): string {
  return `<speak>${inner}</speak>`;
}

const SENTENCE_END = /(?<=[.!?…]["')\]”’]*)\s+/;

export function splitSentences(text: string): string[] {
  return collapseWhitespace(text)
    .split(SENTENCE_END)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/** A cut of a sentence at a word boundary, for the rare sentence that alone is longer than the room there is. */
function cutAtWord(text: string, escapedBudget: number): string {
  let end = text.length;
  while (end > 0 && escapeSsml(text.slice(0, end)).length > escapedBudget) end -= 1;
  const cut = text.slice(0, end);
  const space = cut.lastIndexOf(" ");
  return (space > 0 ? cut.slice(0, space) : cut).trim();
}

export type FitResult = { ssml: string; truncated: boolean };

/**
 * Joins `units` (SSML fragments, already escaped) while they fit in `budget` characters. The cut is always between units. The
 * first unit alone may be too long: then it is shortened at a word boundary (as plain text) instead of dropping everything.
 */
export function fitUnits(units: readonly string[], budget: number): FitResult {
  let used = 0;
  const taken: string[] = [];
  for (const unit of units) {
    if (used + unit.length > budget) {
      if (taken.length === 0) {
        const plain = unit.replace(/<[^>]*>/g, "");
        const unescaped = plain.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");
        const cut = cutAtWord(unescaped, Math.max(0, budget - "<s></s>".length));
        if (cut.length > 0) taken.push(sentence(cut));
      }
      return { ssml: taken.join(""), truncated: true };
    }
    taken.push(unit);
    used += unit.length;
  }
  return { ssml: taken.join(""), truncated: false };
}
