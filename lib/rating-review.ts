/**
 * The rating agent's daily review of suggested ratings (`rr-ratings-<day>`, raised by `ratings suggestions-review`), answered one Story at a time.
 *
 * Each Story is a row: its title, the suggested stars, whether it is a five-star candidate, and the agent's one-line reason, all kept on the
 * request's story link under `rating` (src/papyrus_content/rating_suggestions.py). A person answers a row by using the suggested stars, giving
 * other stars (1 to 5), or leaving it. Only a person rates: the stars are written by the editors' own `setItemStars`, the same path
 * `papyrus ratings confirm` takes, and the row only records what the person chose. The request is answered when every row is, or when the
 * person dismisses it; the generic Accept and Reject are never offered for it. Pure functions only, so the page and its tests share them.
 */
import { reviewStateKey, type ReviewRequest } from "./review-requests";

export const RATINGS_REVIEW_PREFIX = "rr-ratings-";
const CANDIDATE_LABEL = "five-star candidate";
const MAX_HISTORY = 50;

export type RatingRowChoice = "used" | "rated" | "left";
export type RatingRowAnswer = { choice: RatingRowChoice; stars: number | null; by: string; at: string };
/** What the agent stored for a row, and the person's answer once given. */
export type RatingLinkData = { title?: string; stars?: number; candidate?: boolean; reason?: string; answer?: RatingRowAnswer };
export type RatingRow = { story: string; title: string; stars: number; candidate: boolean; reason: string | null; answer: RatingRowAnswer | null };

/** The rating agent's daily review: its id names the day, and it is a soft review about a batch. */
export function isRatingsReview(request: Pick<ReviewRequest, "id" | "mode" | "subject">): boolean {
  return request.id.startsWith(RATINGS_REVIEW_PREFIX) && request.mode === "soft_review" && request.subject.type === "batch";
}

function starsFromLabel(label: string | undefined): number {
  if (label?.endsWith(CANDIDATE_LABEL)) return 5;
  const match = label?.match(/: ([345]) stars suggested$/);
  return match ? Number(match[1]) : 3;
}

/** Every Story the review covers, in the order the agent listed them. */
export function ratingRows(request: Pick<ReviewRequest, "links">): RatingRow[] {
  return request.links.filter((link) => link.type === "story" && link.id).map((link) => {
    const rating = link.rating ?? {};
    const stars = typeof rating.stars === "number" ? rating.stars : starsFromLabel(link.label);
    const title = rating.title || link.label?.replace(/: (?:[345] stars suggested|five-star candidate)$/, "") || String(link.id);
    return { story: String(link.id), title, stars, candidate: rating.candidate ?? stars === 5, reason: rating.reason?.trim() || null, answer: rating.answer ?? null };
  });
}

export function rowsWaiting(request: Pick<ReviewRequest, "links">): RatingRow[] {
  return ratingRows(request).filter((row) => !row.answer);
}

/** "Slow water (4 stars suggested); Deep sea (five-star candidate)": the Stories still waiting, for the card. */
export function ratingRowsSummary(request: Pick<ReviewRequest, "links">): string {
  const waiting = rowsWaiting(request);
  if (!waiting.length) return "Every Story answered.";
  return waiting.map((row) => `${row.title} (${row.candidate ? CANDIDATE_LABEL : `${row.stars} stars suggested`})`).join("; ");
}

/** What a row's answer says, in words. */
export function rowAnswerWords(answer: RatingRowAnswer): string {
  if (answer.choice === "left") return `Left as it is by ${answer.by}`;
  return `${answer.choice === "used" ? "Rated with the suggested" : "Rated"} ${answer.stars} ${answer.stars === 1 ? "star" : "stars"} by ${answer.by}`;
}

/**
 * The update recording one row's answer. When it answers the last row waiting, the request is answered too (it leaves the open partition).
 * Applied with the condition that the request is still open and unchanged since it was read, so two answers never overwrite each other.
 */
export function ratingRowUpdate(request: ReviewRequest, story: string, choice: RatingRowChoice, stars: number | null, by: string, now: Date): Record<string, unknown> {
  if (request.state !== "open") throw new Error("This review is no longer open. Refresh to see how it was answered.");
  if (!ratingRows(request).some((row) => row.story === story)) throw new Error("That Story is not in this review.");
  if (choice !== "left" && !(Number.isInteger(stars) && (stars as number) >= 1 && (stars as number) <= 5)) throw new Error("Choose from 1 to 5 stars.");
  const at = now.toISOString();
  const answer: RatingRowAnswer = { choice, stars: choice === "left" ? null : stars, by, at };
  const links = request.links.map((link) => (link.type === "story" && String(link.id) === story ? { ...link, rating: { ...(link.rating ?? {}), answer } } : link));
  const done = rowsWaiting({ links }).length === 0;
  const history = [...request.history, { at, event: "rating_answered", by, note: `${story}: ${choice}${answer.stars ? ` ${answer.stars}` : ""}` }];
  if (done) history.push({ at, event: "answered", by, note: "every Story answered" });
  return {
    id: request.id, links: JSON.stringify(links), updatedAt: at, history: JSON.stringify(history.slice(-MAX_HISTORY)),
    ...(done ? {
      state: "answered", reviewStateKey: reviewStateKey("answered"), dueAt: null,
      answer: JSON.stringify({ decision: "approve", feedback: "Every Story answered.", steer: null, by, at }),
    } : {}),
  };
}

/** The update dismissing the review: it is answered, and every Story left waiting keeps its suggestion (nothing is rated). */
export function ratingDismissUpdate(request: ReviewRequest, by: string, now: Date): Record<string, unknown> {
  if (request.state !== "open") throw new Error("This review is no longer open. Refresh to see how it was answered.");
  const at = now.toISOString();
  const left = rowsWaiting(request).length;
  const feedback = left ? `Dismissed; ${left} ${left === 1 ? "suggestion stays" : "suggestions stay"} on the Stories, unrated.` : "Dismissed.";
  const history = [...request.history, { at, event: "answered", by, note: "dismissed" }].slice(-MAX_HISTORY);
  return {
    id: request.id, state: "answered", reviewStateKey: reviewStateKey("answered"), dueAt: null, updatedAt: at, history: JSON.stringify(history),
    answer: JSON.stringify({ decision: "feedback", feedback, steer: null, by, at }),
  };
}
