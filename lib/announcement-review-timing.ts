/**
 * Administration > Announcements, the "Review and timing" card (PPY-e2829f): how X story posts are reviewed and how long after drafting they post.
 *
 * The review is the `announce` rung of the site's agent policy for the channel `x` and the kind `story_published` (`announcements_review_show` and
 * `announcements_review_set`); the timing is that scope's entry in the announcement settings' `editWindows`. Words and validation hints only: the
 * agent-policy function and the announcements function check every rule again (`announcements/review_policy.py`, `announcements/edit_windows.py`).
 */
import type { EditWindow } from "./announcements-model";

export type ReviewApproval = "hard" | "soft" | "none";

/** The one scope this card sets: posts on X when a Story is published. */
export const X_STORY_POSTS = { channel: "x", kind: "story_published" } as const;

/** The reason recorded with a review change when the person types none. Each change is a version of the agent policy with who, when and why. */
export const DEFAULT_REVIEW_REASON = "Set in the newsroom's Announcements settings.";

export const REVIEW_OPTIONS: { value: ReviewApproval; label: string; detail: string }[] = [
  { value: "hard", label: "A person approves each post", detail: "Nothing goes out until someone approves it." },
  { value: "soft", label: "Posts on schedule unless someone steps in", detail: "It goes out at its time unless a person stops or changes it first." },
  { value: "none", label: "Posts right away", detail: "No one reviews it. The first person to see it is a reader." },
];

export function reviewLabel(approval: string | null | undefined): string {
  return REVIEW_OPTIONS.find((option) => option.value === approval)?.label ?? "Not set";
}

/** What `announcements_review_show` answers for a channel and kind (src/papyrus_content/announcements/review_handlers.py `show_review`). */
export type ReviewShown = {
  policyVersion: number;
  approval: string | null;
  rung: string;
  overrides: { scope: Record<string, string>; approval: string | null; rung: string }[];
  chosen?: { approval: ReviewApproval | null; rung: string; policy: string; reason: string | null } | null;
};

/** The current review of X story posts in words: what it is, and where it comes from (the publication, or an override, and the policy version). */
export function currentReviewText(shown: ReviewShown): string {
  const chosen = shown.chosen;
  if (!chosen) return "Not set.";
  if (!chosen.approval) return `No post is prepared: ${chosen.reason ?? `the announce agent is at ${chosen.rung}`}.`;
  return `${reviewLabel(chosen.approval)}. From the ${chosen.policy}.`;
}

/** The narrowest edit window that fits a kind and channel, as `edit_windows.resolve` chooses it. */
export function resolveWindow(windows: readonly EditWindow[], kind: string, channel: string): EditWindow | null {
  const fits = windows.filter((entry) => (entry.kind ?? null) === null || entry.kind === kind).filter((entry) => (entry.channel ?? null) === null || entry.channel === channel);
  const rank = (entry: EditWindow) => (entry.kind && entry.channel ? 4 : 0) + (entry.kind ? 2 : 0) + (entry.channel ? 1 : 0);
  return fits.reduce<EditWindow | null>((best, entry) => (best === null || rank(entry) > rank(best) ? entry : best), null);
}

export type TimingFields = { windowMinutes: string; lockLeadMinutes: string };

/** The fields as the page first shows them: the window that applies to X story posts today, or blank when none does. */
export function timingFields(windows: readonly EditWindow[] | undefined): TimingFields {
  const found = resolveWindow(windows ?? [], X_STORY_POSTS.kind, X_STORY_POSTS.channel);
  return found ? { windowMinutes: String(found.windowMinutes), lockLeadMinutes: String(found.lockLeadMinutes ?? 0) } : { windowMinutes: "", lockLeadMinutes: "" };
}

/** Where today's timing comes from, when it is not the entry for X story posts itself; null when it is, or when there is none. */
export function inheritedTimingText(windows: readonly EditWindow[] | undefined): string | null {
  const found = resolveWindow(windows ?? [], X_STORY_POSTS.kind, X_STORY_POSTS.channel);
  if (!found || (found.kind === X_STORY_POSTS.kind && found.channel === X_STORY_POSTS.channel)) return null;
  const scope = found.kind ? `every ${found.kind.replace(/_/g, " ")} post` : found.channel ? `every post on ${found.channel}` : "every kind and channel";
  return `Today this comes from the setting for ${scope}. Saving here sets X story posts on their own.`;
}

const WHOLE = /^\d+$/;

/** Why the fields cannot be saved, in a plain sentence, as `edit_windows.validate` would say it; null when they can. Both blank means no window. */
export function timingProblem(fields: TimingFields): string | null {
  const window = fields.windowMinutes.trim();
  const lead = fields.lockLeadMinutes.trim();
  if (window === "" && lead === "") return null;
  if (!WHOLE.test(window)) return "Post after is a whole number of minutes, zero or more.";
  if (lead !== "" && !WHOLE.test(lead)) return "Lock before is a whole number of minutes, zero or more.";
  if (Number(lead || 0) > Number(window)) return `The lock comes ${Number(lead)} minutes before the post, which is more than the ${Number(window)} minutes after the draft. Make it ${Number(window)} or less.`;
  return null;
}

/** The settings' edit windows with the entry for X story posts set from the fields (or taken away when both are blank). Every other entry is kept as it was. */
export function withXStoryTiming(windows: readonly EditWindow[] | undefined, fields: TimingFields): EditWindow[] {
  const others = (windows ?? []).filter((entry) => !(entry.kind === X_STORY_POSTS.kind && entry.channel === X_STORY_POSTS.channel));
  if (fields.windowMinutes.trim() === "" && fields.lockLeadMinutes.trim() === "") return others;
  return [...others, { kind: X_STORY_POSTS.kind, channel: X_STORY_POSTS.channel, windowMinutes: Number(fields.windowMinutes.trim()), lockLeadMinutes: Number(fields.lockLeadMinutes.trim() || 0) }];
}

/** True when the fields would change what the settings say for X story posts. */
export function timingChanged(windows: readonly EditWindow[] | undefined, fields: TimingFields): boolean {
  const exact = (windows ?? []).find((entry) => entry.kind === X_STORY_POSTS.kind && entry.channel === X_STORY_POSTS.channel) ?? null;
  const wanted = withXStoryTiming(windows, fields).find((entry) => entry.kind === X_STORY_POSTS.kind && entry.channel === X_STORY_POSTS.channel) ?? null;
  if (exact === null || wanted === null) return exact !== wanted;
  return exact.windowMinutes !== wanted.windowMinutes || (exact.lockLeadMinutes ?? 0) !== (wanted.lockLeadMinutes ?? 0);
}

const minutes = (count: number) => `${count} minute${count === 1 ? "" : "s"}`;

/** One plain line: what soft and hard review do at the time the fields give. */
export function timingExplanation(fields: TimingFields): string {
  if (timingProblem(fields)) return "Fix the numbers above to see what happens at that time.";
  const window = fields.windowMinutes.trim();
  if (window === "") return "No time is set: with soft review a post goes as soon as it is allowed; with a person's approval it waits for that approval.";
  const lead = Number(fields.lockLeadMinutes.trim() || 0);
  const lock = lead > 0 ? `, and stops taking edits ${minutes(lead)} before` : "";
  return `${minutes(Number(window))} after the draft is made, a soft post goes out unless someone has stopped it${lock}; a post that needs a person's approval waits for one and shows as Overdue until then.`;
}
