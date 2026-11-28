"use client";

import { CircleCheckIcon, Loader2Icon, StarIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { rowAnswerWords, type RatingRow, type RatingRowChoice } from "../lib/rating-review";
import { formatWhen } from "../lib/review-requests";
import { requestCaption } from "../lib/notification-feed";

/** Answers one row: the stars go through the editors' own `setItemStars` (only a person rates), then the row records the choice. Throws a sentence. */
export type RatingRowAction = (item: NeedsMeEntry, row: RatingRow, choice: RatingRowChoice, stars: number | null) => Promise<void>;
/** Dismisses the whole review; every Story left waiting keeps its suggestion and is not rated. Throws a sentence. */
export type RatingDismissAction = (item: NeedsMeEntry) => Promise<void>;

type Payload = Extract<NeedsMeEntry["payload"], { kind: "ratings" }>;

const BUTTON = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const STAR_CHOICES = [1, 2, 3, 4, 5] as const;

function starWords(stars: number): string {
  return `${stars} ${stars === 1 ? "star" : "stars"}`;
}

function Row({ item, row, href, disabledReason, onAnswer }: { item: NeedsMeEntry; row: RatingRow; href: string; disabledReason: string | null; onAnswer?: RatingRowAction }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  const open = item.decisionState === "open" && !row.answer;
  const blocked = Boolean(disabledReason) || !onAnswer || busy !== null;
  const answer = async (key: string, choice: RatingRowChoice, stars: number | null) => {
    if (blocked || !onAnswer) return;
    setBusy(key);
    setError(null);
    try {
      await onAnswer(item, row, choice, stars);
      setChoosing(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Your answer could not be saved.");
    } finally {
      setBusy(null);
    }
  };
  return (
    <li className="space-y-2 rounded-[16px] bg-[var(--feed-control)] p-3" data-rating-row={row.story} data-rating-row-state={row.answer ? row.answer.choice : "waiting"}>
      <div className="space-y-1">
        <Link className="break-words font-semibold leading-snug text-primary underline underline-offset-4" data-rating-row-title href={href}>{row.title}</Link>
        <p className="flex flex-wrap items-center gap-1.5 text-sm" data-rating-row-suggested>
          <StarIcon aria-hidden="true" className="size-4 shrink-0" />
          {row.candidate ? "Five-star candidate: only a person gives five stars" : `${starWords(row.stars)} suggested`}
        </p>
        <p className="break-words text-sm text-muted-foreground" data-rating-row-reason>{row.reason ? `Why: ${row.reason}` : "No reason was recorded for this suggestion."}</p>
      </div>
      {row.answer ? (
        <p className="flex items-center gap-1.5 text-sm font-medium" data-rating-row-answer><CircleCheckIcon aria-hidden="true" className="size-4" />{rowAnswerWords(row.answer)} on {formatWhen(row.answer.at)}.</p>
      ) : open ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2" data-rating-row-actions>
            <button className={cn(BUTTON, "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)] hover:opacity-90")} data-rating-use={row.stars} disabled={blocked} onClick={() => void answer("use", "used", row.stars)} type="button">
              {busy === "use" ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <StarIcon aria-hidden="true" className="size-4" />}Use {starWords(row.stars)}
            </button>
            <button aria-expanded={choosing} className={cn(BUTTON, "bg-[var(--feed-footer)] text-foreground hover:bg-[var(--feed-footer)]/70")} data-rating-other disabled={blocked} onClick={() => setChoosing((current) => !current)} type="button">
              Other stars
            </button>
            <button className={cn(BUTTON, "bg-[var(--feed-footer)] text-foreground hover:bg-[var(--feed-footer)]/70")} data-rating-leave disabled={blocked} onClick={() => void answer("leave", "left", null)} type="button">
              {busy === "leave" ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : null}Leave it
            </button>
          </div>
          {choosing ? (
            <div aria-label={`Your stars for ${row.title}`} className="flex flex-wrap gap-1.5" data-rating-choices role="group">
              {STAR_CHOICES.map((stars) => (
                <button className={cn(BUTTON, "min-w-10 bg-[var(--feed-footer)] text-foreground hover:bg-[var(--feed-footer)]/70")} data-rating-choice={stars} disabled={blocked} key={stars} onClick={() => void answer(`stars-${stars}`, stars === row.stars ? "used" : "rated", stars)} type="button">
                  {busy === `stars-${stars}` ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : null}{starWords(stars)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" data-rating-row-closed>Not answered here; the suggestion stays on the Story.</p>
      )}
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
    </li>
  );
}

/**
 * The rating agent's daily review, one row per Story: its title (linked to the Story), the suggested stars and the agent's reason, and three answers.
 * There is no Accept or Reject: the review is answered when every row is, or when the person dismisses it.
 */
export function RatingsBody({ item, payload, demo, disabledReason, onRatingRow, onRatingDismiss }: {
  item: NeedsMeEntry; payload: Payload; demo: boolean; disabledReason: string | null; onRatingRow?: RatingRowAction; onRatingDismiss?: RatingDismissAction;
}) {
  const { request, rows } = payload;
  const [dismissing, setDismissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const waiting = rows.filter((row) => !row.answer).length;
  const open = item.decisionState === "open";
  const dismiss = async () => {
    if (!onRatingDismiss || dismissing || disabledReason) return;
    setDismissing(true);
    setError(null);
    try { await onRatingDismiss(item); } catch (failure) { setError(failure instanceof Error ? failure.message : "The review could not be dismissed."); } finally { setDismissing(false); }
  };
  return (
    <div className="space-y-4" data-ratings-review={request.id} data-review-request={request.id}>
      <header className="space-y-1.5">
        <h2 className="break-words text-xl font-bold leading-tight tracking-tight text-foreground">{request.reason}</h2>
        <p className="break-words text-base text-muted-foreground" data-review-ask>For each Story, use the suggested stars, choose other stars, or leave it. The agent never changes a rating; your rating always wins.</p>
      </header>
      <section aria-label="The Stories in this review" className="space-y-2">
        <h3 className="text-sm font-medium text-foreground" data-ratings-waiting>{open ? `${waiting} of ${rows.length} still to answer` : `${rows.length} ${rows.length === 1 ? "Story" : "Stories"}`}</h3>
        <ul className="space-y-2" data-ratings-rows>
          {rows.map((row) => (
            <Row
              disabledReason={disabledReason} href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(row.story)}`, demo)} item={item} key={row.story}
              onAnswer={onRatingRow} row={row}
            />
          ))}
        </ul>
      </section>
      <p className="text-xs text-muted-foreground" data-draft-caption>{requestCaption(request)}{request.state === "answered" && request.answer ? ` · answered ${formatWhen(request.answer.at)}` : ""}</p>
      {open ? (
        <div className="space-y-2 rounded-[20px] bg-[var(--feed-footer)] p-3" data-ratings-dismiss-panel>
          <button className={cn(BUTTON, "w-full bg-[var(--feed-control)] text-foreground hover:bg-[var(--feed-control)]/70")} data-ratings-dismiss disabled={dismissing || Boolean(disabledReason) || !onRatingDismiss} onClick={() => void dismiss()} type="button">
            {dismissing ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <XIcon aria-hidden="true" className="size-4" />}Dismiss this review
          </button>
          <p className="text-xs text-muted-foreground">Dismissing rates nothing: every Story still waiting keeps its suggestion.</p>
          {disabledReason ? <p className="text-xs text-muted-foreground" data-review-disabled-reason>{disabledReason}</p> : null}
          {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
        </div>
      ) : request.answer ? (
        <p className="text-sm" data-ratings-answered>{request.answer.feedback ?? "Answered"} ({request.answer.by}, {formatWhen(request.answer.at)})</p>
      ) : null}
    </div>
  );
}
