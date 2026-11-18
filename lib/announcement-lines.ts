/**
 * What the Story drawer and the Announcements list read (PPY-e4ae3a): one line for each Delivery, in words and marks. The words and the name of each mark (a Lucide icon) are said
 * once, by the backend (`src/papyrus_content/announcements/lines.py`), so the console, `papyrus announcements` and the agents' tools show the same sentence. This module holds the
 * shapes of the answer, the door that asks for it, and the few plain labels the page adds (a channel's name, a kind's name).
 */
import type { ImageEnvelope, ImageOperations } from "./images/operations.generated";

export type Marked = { words: string; mark: string };

/** A Delivery's review: `approval` is none, soft or hard (the words say what that means). Null for a Delivery that will not go. */
export type ReviewLine = Marked & { approval: "none" | "soft" | "hard" | string };

/** What needs a person's eye: Overdue (due, with no attempt), Outcome unknown (an attempt with no answer yet, until Caducus settles it), or a failed check. */
export type AttentionLine = Marked & { kind: "overdue" | "outcome_unknown" | "check_failed"; since?: string };

export type AttemptLine = Marked & { number: number; at?: string | null; outcome: "started" | "sent" | "refused" | "unknown"; code?: string | null };

export type DeliveryLine = Marked & {
  id: string;
  announcementId: string;
  channel: string;
  accountId: string;
  generation?: number;
  state: string;
  approval?: ReviewLine | null;
  releaseAt?: string | null;
  lockAt?: string | null;
  dueAt?: string | null;
  waitingFor?: string | null;
  nextAttemptAt?: string | null;
  blockedReason?: string | null;
  attempts: number;
  lastAttempt?: AttemptLine | null;
  resultUrl?: string | null;
  attention: AttentionLine[];
};

/** The one open review flag of an Announcement whose draft was blocked: shown once, however many channels are blocked. */
export type ReviewFlagLine = Marked & { id: string; reason: string; ask?: string | null; raisedAt?: string | null };

export type AnnouncementEntry = {
  id: string;
  kind: string;
  state: string;
  releaseAt: string;
  trigger?: string | null;
  createdBy?: string | null;
  versionLookedAt?: number | null;
  reviewFlag?: ReviewFlagLine | null;
  deliveries: DeliveryLine[];
  /** In the list: the Stories the Announcement is about. */
  stories?: { lineageId: string; title: string; versionLookedAt?: number | null }[];
};

export type AnnouncementsWhere = { story: string; announcements: AnnouncementEntry[] };
export type AnnouncementsRecent = { announcements: AnnouncementEntry[]; overdue: DeliveryLine[]; next: string | null };

type DoorOperation = "announcements_where" | "announcements_recent";
type DoorResult = { announcements_where: AnnouncementsWhere; announcements_recent: AnnouncementsRecent };

/** The announcements door: reads only. The console's own sends GraphQL (`lib/announcements-door-client.ts`); the demo answers from seeded data. */
export type AnnouncementsDoor = <Name extends DoorOperation>(op: Name, input: ImageOperations[Name]["input"]) => Promise<ImageEnvelope<DoorResult[Name]>>;

/** The answer, or the plain sentence of why there is none. */
export async function readDoor<Name extends DoorOperation>(door: AnnouncementsDoor, op: Name, input: ImageOperations[Name]["input"]): Promise<DoorResult[Name]> {
  let envelope: ImageEnvelope<DoorResult[Name]>;
  try {
    envelope = await door(op, input);
  } catch (error) {
    throw new Error(error instanceof Error && error.message ? error.message : "The announcements service did not answer. It may not be on this site yet.");
  }
  if (!envelope.ok) throw new Error(envelope.error.message || "The announcements service did not answer.");
  return envelope.result;
}

/** A channel's name for a person: X, Email, and any other channel with a capital. */
export function channelName(channel: string): string {
  return channel === "x" ? "X" : channel.charAt(0).toUpperCase() + channel.slice(1);
}

const KIND_NAMES: Record<string, string> = { story_published: "Story published", roundup: "Roundup", correction: "Correction" };

export function kindName(kind: string): string {
  return KIND_NAMES[kind] ?? (kind.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase()));
}

/** What a Delivery is waiting for, in words, when it names a time. Empty when it waits for nothing. */
export function waitingWords(line: DeliveryLine, when: (iso: string) => string): string {
  if (line.waitingFor && line.nextAttemptAt) return `Waiting for the ${line.waitingFor} until ${when(line.nextAttemptAt)}`;
  if (line.state === "drafted" || line.state === "ready") {
    if (line.lockAt && line.lockAt !== line.releaseAt) return `Goes ${when(line.releaseAt ?? line.lockAt)}, locks ${when(line.lockAt)}`;
    if (line.releaseAt) return `Goes ${when(line.releaseAt)}`;
  }
  return "";
}
