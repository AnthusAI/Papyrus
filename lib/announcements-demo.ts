import type { AnnouncementEntry, AnnouncementsDoor, AnnouncementsRecent, AnnouncementsWhere, DeliveryLine } from "./announcement-lines";

/**
 * Seeded announcements for `?demo=1` and the local preview: clearly fake Stories and accounts, no real address, and no channel that sends. Times are relative to now, so the
 * Overdue line is always overdue and the Delivery that is not due is always ahead. The words and marks are the ones the backend says (`lines.py`, `approval_words.py`).
 * X stays off: nothing here is, or could be, sent.
 */
const HOUR = 3_600_000;
const at = (hours: number, now: number) => new Date(now + hours * HOUR).toISOString().replace(/\.\d{3}Z$/, "Z");

const REVIEW = {
  none: { words: "Released automatically by publication policy", mark: "bot", approval: "none" },
  soft: { words: "Goes at its lock time unless a person stops it (publication policy)", mark: "hourglass", approval: "soft" },
  hard: { words: "Waits for a person to release it (override: kind roundup)", mark: "hand", approval: "hard" },
  person: { words: "Released by a person (Preview editor)", mark: "user-check", approval: "hard" },
} as const;

function line(announcementId: string, channel: string, accountId: string, fields: Partial<DeliveryLine> & Pick<DeliveryLine, "state" | "words" | "mark">): DeliveryLine {
  return {
    id: `${announcementId}#${channel}#${accountId}#g1`, announcementId, channel, accountId, generation: 1, approval: null, releaseAt: null, lockAt: null, dueAt: null, waitingFor: null,
    nextAttemptAt: null, blockedReason: null, attempts: 0, lastAttempt: null, resultUrl: null, attention: [], ...fields,
  };
}

/** The two published Stories of the local preview (lib/local-preview-seed.ts), as the preview titles them. */
const HARBOR = { lineageId: "preview-item-lineage-published-0", title: "Published: harbor safety review", versionLookedAt: 1 };
const LIGHTHOUSE = { lineageId: "preview-item-lineage-published-1", title: "Published: the lighthouse keepers' archive", versionLookedAt: 1 };

/**
 * Every demo Announcement. The harbor Story was posted, was corrected (the correction's attempt has no answer yet), and is in a roundup that waits for a person. The lighthouse Story
 * is in that roundup too, has an overdue Delivery and has a blocked draft with its one review flag.
 */
export function demoAnnouncements(now: number = Date.now()): AnnouncementEntry[] {
  const posted = "announcement-demo-posted", stuck = "announcement-demo-stuck", unsure = "announcement-demo-correction", roundup = "announcement-demo-roundup";
  return [
    {
      id: roundup, kind: "roundup", state: "planned", releaseAt: at(20, now), createdBy: "announce", trigger: "weekly roundup", versionLookedAt: null, reviewFlag: null, stories: [HARBOR, LIGHTHOUSE],
      deliveries: [line(roundup, "email", "site-one", { state: "drafted", words: "Draft", mark: "pencil-line", approval: REVIEW.hard, releaseAt: at(20, now), lockAt: at(20, now), dueAt: at(20, now) })],
    },
    {
      id: unsure, kind: "correction", state: "released", releaseAt: at(-1, now), createdBy: "announce", trigger: "story corrected", versionLookedAt: 2, reviewFlag: null, stories: [HARBOR],
      deliveries: [line(unsure, "x", "handle-demo", {
        state: "sending", words: "Sending", mark: "send", approval: REVIEW.none, releaseAt: at(-1, now), lockAt: at(-1, now), attempts: 1,
        lastAttempt: { number: 1, at: at(-0.5, now), outcome: "started", words: "Outcome unknown", mark: "?" },
        attention: [{ kind: "outcome_unknown", words: "Outcome unknown", mark: "circle-help", since: at(-0.5, now) }],
      })],
    },
    {
      id: stuck, kind: "story_published", state: "released", releaseAt: at(-3, now), createdBy: "announce", trigger: "story published", versionLookedAt: 1,
      reviewFlag: { id: "blocked-draft-demo", words: "Review requested: a draft was blocked", mark: "flag", reason: "A draft was blocked: the checks on its words failed: the post is over 280 characters.", ask: "email site-one: the words did not pass their checks, so nothing will be sent. Look at the draft and decide what should go out.", raisedAt: at(-2.5, now) },
      stories: [LIGHTHOUSE],
      deliveries: [
        line(stuck, "email", "site-one", {
          state: "blocked", words: "Blocked: check failed", mark: "ban", approval: REVIEW.soft, blockedReason: "check failed", releaseAt: at(-3, now), lockAt: at(-3, now),
          attention: [{ kind: "check_failed", words: "The checks on its words failed", mark: "shield-alert", since: at(-2.5, now) }],
        }),
        line(stuck, "x", "handle-demo", {
          state: "ready", words: "Ready", mark: "calendar-check", approval: REVIEW.none, releaseAt: at(-3, now), lockAt: at(-3, now), dueAt: at(-3, now),
          attention: [{ kind: "overdue", words: "Overdue", mark: "clock-alert", since: at(-3, now) }],
        }),
      ],
    },
    {
      id: posted, kind: "story_published", state: "released", releaseAt: at(-30, now), createdBy: "announce", trigger: "story published", versionLookedAt: 1, reviewFlag: null, stories: [HARBOR],
      deliveries: [
        line(posted, "email", "site-one", {
          state: "sent", words: "Sent", mark: "circle-check", approval: REVIEW.person, releaseAt: at(-30, now), lockAt: at(-30, now), attempts: 1,
          lastAttempt: { number: 1, at: at(-29.9, now), outcome: "sent", words: "Sent", mark: "✓" },
        }),
        line(posted, "x", "handle-demo", { state: "dry_run", words: "Dry run: not sent", mark: "flask-conical", releaseAt: at(-30, now), lockAt: at(-30, now) }),
      ],
    },
  ];
}

/** The Announcements a demo Story is about, as the drawer reads them (the Story's titles are the list's). */
function whereDemo(lineageId: string, now: number): AnnouncementsWhere {
  const announcements = demoAnnouncements(now)
    .filter((entry) => entry.stories?.some((story) => story.lineageId === lineageId))
    .map(({ stories: _stories, ...entry }) => entry);
  return { story: lineageId, announcements };
}

function recentDemo(now: number): AnnouncementsRecent {
  const announcements = demoAnnouncements(now);
  return { announcements, overdue: announcements.flatMap((entry) => entry.deliveries.filter((delivery) => delivery.attention.some((item) => item.kind === "overdue"))), next: null };
}

export function createDemoAnnouncementsDoor(now: () => number = Date.now): AnnouncementsDoor {
  return (async (op: string, input: { story?: string }) => {
    const base = { ok: true as const, op, publication: "demo", warnings: [] };
    if (op === "announcements_where") return { ...base, result: whereDemo(String(input.story ?? ""), now()) };
    if (op === "announcements_recent") return { ...base, result: recentDemo(now()) };
    if (op === "announcements_account_status") return { ...base, result: { mode: "on", paused: false, standing: "$0.60 spent of $10.00 this cycle", postCount: 3,
      suggestion: { eligibleCount: 4, windowDays: 60, postsPerMonth: 2, dollarsPerMonth: 0.4, sentence: "At your pace, about 2 posts and $0.40 per month" } } };
    return { ok: false as const, op, error: { code: "unknown_operation", message: `The demo has no ${op}.`, retryable: false, details: {} } };
  }) as unknown as AnnouncementsDoor;
}
