/**
 * What to look for when the editor gives no search target: a few plain words from the Story's title and summary. No model, no cost.
 * Title words come first in order; the summary adds its most repeated other words. The editor sees the result and can replace it.
 */
const STOP_WORDS = new Set((
  "a an and are as at be been but by can could did do does for from had has have how if in into is it its more most new no not of on or our out over " +
  "per says say said than that the their them then there these they this those to up was we were what when where which while who why will with would " +
  "you your about after amid also all any being between both during each few here just like make many may much now off one only other some such " +
  "than too very via report reports study first last year years week today"
).split(/\s+/));
const WORD = /[\p{L}\p{N}][\p{L}\p{N}'-]*/gu;
export const TARGET_WORDS = 5;
const FROM_SUMMARY = 2;

function words(text: string): string[] {
  return (text.match(WORD) ?? []).map((word) => word.replace(/^['-]+|['-]+$/g, "")).filter((word) => word.length >= 3 && !STOP_WORDS.has(word.toLowerCase()) && !/^\d+$/.test(word));
}

export function deriveSearchTarget(title: string, summary: string): string {
  const chosen: string[] = [];
  const seen = new Set<string>();
  const take = (word: string) => {
    const key = word.toLowerCase();
    if (seen.has(key) || chosen.length >= TARGET_WORDS) return;
    seen.add(key);
    chosen.push(word);
  };
  const fromTitle = words(title);
  fromTitle.slice(0, TARGET_WORDS - 1).forEach(take);
  const counts = new Map<string, { word: string; count: number; first: number }>();
  words(summary).forEach((word, index) => {
    const key = word.toLowerCase();
    const entry = counts.get(key);
    if (entry) entry.count += 1;
    else counts.set(key, { word, count: 1, first: index });
  });
  const ranked = [...counts.values()].filter((entry) => !seen.has(entry.word.toLowerCase())).sort((a, b) => b.count - a.count || a.first - b.first);
  const room = Math.min(FROM_SUMMARY, TARGET_WORDS - chosen.length);
  ranked.slice(0, Math.max(room, chosen.length === 0 ? TARGET_WORDS : 0)).forEach((entry) => take(entry.word));
  return chosen.join(" ");
}
