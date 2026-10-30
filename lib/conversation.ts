/**
 * Conversations: Messages written about a Reference (later a Story, or nothing at all). One conversation per thing, held in one
 * MessageThread found by its anchor key. Pure helpers only, so the browser and the tests share them.
 */

export const CONVERSATION_FEED_KEY = "conversations";
export const REFERENCE_CONVERSATION_KIND = "reference_conversation";
export const STORY_CONVERSATION_KIND = "story_conversation";
export const GENERAL_CONVERSATION_KIND = "conversation";

/** What a conversation is about. `none` is a conversation that is about nothing but itself. */
export type ConversationAnchor =
  | { kind: "reference" | "item"; lineageId: string; /** The version id when it differs from the lineage id. */ id?: string; title?: string }
  | { kind: "none"; lineageId?: undefined; title?: string };

/** A Message as the conversation shows it. */
export type ConversationMessage = {
  id: string;
  parentMessageId: string | null;
  authorLabel: string;
  content: string;
  createdAt: string;
  sequenceNumber: number;
  /** The sub of the person who wrote it: only they can edit it. */
  authorSub?: string | null;
  /** Their profile, where their display name lives. */
  authorUserProfileId?: string | null;
  /** When the author last changed the text. */
  editedAt?: string | null;
  /** A deleted Message keeps its place (replies stay under it) but has no text. */
  deleted?: boolean;
  deletedAt?: string | null;
  /** True while an optimistic Message waits for the save. */
  pending?: boolean;
};

/** Who is looking: what they may change is decided from this (an author edits their own; an admin removes anyone's). */
export type ConversationViewer = { sub: string | null; isAdmin: boolean };

export const NO_VIEWER: ConversationViewer = { sub: null, isAdmin: false };

/** Only the author edits a Message, and not one that is deleted or still being saved. */
export function canEditMessage(viewer: ConversationViewer | undefined, message: ConversationMessage): boolean {
  return Boolean(viewer?.sub && message.authorSub && message.authorSub === viewer.sub && !message.deleted && !message.pending);
}

/** The author deletes their own; an admin deletes anyone's. */
export function canDeleteMessage(viewer: ConversationViewer | undefined, message: ConversationMessage): boolean {
  if (!viewer || message.deleted || message.pending) return false;
  return viewer.isAdmin || Boolean(viewer.sub && message.authorSub && message.authorSub === viewer.sub);
}

/** Only the person who started a conversation, or an admin, renames it. */
export function canRenameThread(viewer: ConversationViewer | undefined, thread: { createdBySub?: string | null }): boolean {
  if (!viewer) return false;
  return viewer.isAdmin || Boolean(viewer.sub && thread.createdBySub && thread.createdBySub === viewer.sub);
}

/**
 * The name to show. The label saved with the Message is the author's display name (it travels with the Message, because other
 * editors cannot read profiles); an older Message saved an email there, so a profile name, when it can be read, comes before an
 * email's first part.
 */
export function messageAuthorName(message: Pick<ConversationMessage, "authorLabel" | "authorUserProfileId">, names?: ReadonlyMap<string, string>): string {
  const label = String(message.authorLabel ?? "").trim();
  if (label && !label.includes("@")) return label;
  const profileName = message.authorUserProfileId ? names?.get(message.authorUserProfileId)?.trim() : "";
  return profileName || conversationAuthorName(label);
}

export type ConversationReply = { message: ConversationMessage; answers: string | null };
export type ConversationRoot = { message: ConversationMessage; replies: ConversationReply[] };

function slug(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 120) || "thing";
}

/** `reference#<lineageId>`, `item#<lineageId>`, or null when the conversation is anchored to nothing. */
export function conversationAnchorKey(anchor: ConversationAnchor): string | null {
  return anchor.kind === "none" || !anchor.lineageId?.trim() ? null : `${anchor.kind}#${anchor.lineageId.trim()}`;
}

export function conversationThreadKind(anchor: ConversationAnchor): string {
  return anchor.kind === "reference" ? REFERENCE_CONVERSATION_KIND : anchor.kind === "item" ? STORY_CONVERSATION_KIND : GENERAL_CONVERSATION_KIND;
}

/** The thread id follows the anchor, so two editors starting the same conversation at once collide on create instead of splitting it. */
export function conversationThreadId(anchor: ConversationAnchor): string {
  const key = conversationAnchorKey(anchor);
  if (!key) throw new Error("A conversation without an anchor needs its own thread id.");
  return `message-thread-conversation-${slug(key)}`;
}

export function conversationMessageId(threadId: string, sequenceNumber: number): string {
  return `message-conversation-${slug(threadId)}-${String(sequenceNumber).padStart(4, "0")}`;
}

/** One more than the highest sequence number in use. */
export function nextConversationSequence(existing: ReadonlyArray<{ sequenceNumber?: number | null }>): number {
  return Math.max(0, ...existing.map((message) => Number(message.sequenceNumber || 0))) + 1;
}

/** A create that lost a race for its sequence number (the id derives from the number, so the second writer collides). */
export function isSequenceConflict(error: unknown): boolean {
  const text = error instanceof Error ? error.message : typeof error === "string" ? error : JSON.stringify(error ?? "");
  return /conditional|already exists|duplicate|ConditionalCheckFailed/i.test(text);
}

/** "ryan@example.test" is shown as "ryan"; a name stays as it is. */
export function conversationAuthorName(label: string | null | undefined): string {
  const text = String(label ?? "").trim();
  if (!text) return "Someone";
  const at = text.indexOf("@");
  return at > 0 ? text.slice(0, at) : text;
}

/**
 * Top-level Messages in order, each with its replies. A reply to a reply stays flat under the same root and says who it answers.
 * A reply whose parent is missing is shown as a top-level Message rather than lost.
 */
export function buildConversationTree(messages: ReadonlyArray<ConversationMessage>, nameOf: (message: ConversationMessage) => string = (message) => conversationAuthorName(message.authorLabel)): ConversationRoot[] {
  const sorted = [...messages].sort((a, b) => a.sequenceNumber - b.sequenceNumber || a.createdAt.localeCompare(b.createdAt));
  const byId = new Map(sorted.map((message) => [message.id, message]));
  const rootOf = (message: ConversationMessage): string => {
    let current = message;
    const seen = new Set<string>();
    while (current.parentMessageId && byId.has(current.parentMessageId) && !seen.has(current.id)) {
      seen.add(current.id);
      current = byId.get(current.parentMessageId)!;
    }
    return current.id;
  };
  const roots = new Map<string, ConversationRoot>();
  for (const message of sorted) {
    if (rootOf(message) === message.id) roots.set(message.id, { message, replies: [] });
  }
  for (const message of sorted) {
    const root = roots.get(rootOf(message));
    if (!root || root.message.id === message.id) continue;
    const parent = message.parentMessageId ? byId.get(message.parentMessageId) : undefined;
    root.replies.push({ message, answers: parent && parent.id !== root.message.id ? nameOf(parent) : null });
  }
  return [...roots.values()];
}

/** Short relative time: "now", "5m", "3h", "2d". */
export function conversationAge(createdAt: string, now: number): string {
  const time = Date.parse(createdAt);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((now - time) / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/** The first line of a message, trimmed to fit a card: what a thread shows as its latest message. */
export function conversationPreviewLine(content: string | null | undefined, max = 140): string {
  const line = String(content ?? "").split("\n").map((part) => part.trim()).find(Boolean) ?? "";
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}

function threadMetadataObject(metadata: unknown): Record<string, unknown> {
  if (metadata && typeof metadata === "object" && !Array.isArray(metadata)) return metadata as Record<string, unknown>;
  if (typeof metadata !== "string" || !metadata.trim()) return {};
  try {
    const parsed = JSON.parse(metadata);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

/** The thread's metadata (a JSON string) with the author of its latest message recorded, so a list can show who spoke last without reading messages. */
export function threadMetadataWithLastAuthor(metadata: unknown, authorLabel: string): string {
  return JSON.stringify({ ...threadMetadataObject(metadata), lastAuthorLabel: authorLabel });
}

/** Who wrote the latest message, as recorded on the thread; null for a thread that predates the record. */
export function threadLastAuthorLabel(metadata: unknown): string | null {
  const label = threadMetadataObject(metadata).lastAuthorLabel;
  return typeof label === "string" && label.trim() ? label : null;
}

export function messageCountLabel(count: number): string {
  return `${count} ${count === 1 ? "message" : "messages"}`;
}

/**
 * Creates a Message with the next sequence number. The id derives from the number, so when another writer took it the create is
 * refused and this tries the next number, up to `attempts` times. `list` returns the Messages already in the thread.
 */
export async function createWithSequenceRetry<Message>(input: {
  list: () => Promise<ReadonlyArray<{ sequenceNumber?: number | null }>>;
  create: (sequenceNumber: number) => Promise<Message>;
  attempts?: number;
}): Promise<{ created: Message; sequenceNumber: number }> {
  const attempts = input.attempts ?? 5;
  let sequenceNumber = nextConversationSequence(await input.list());
  for (let attempt = 1; ; attempt += 1) {
    try {
      return { created: await input.create(sequenceNumber), sequenceNumber };
    } catch (error) {
      if (!isSequenceConflict(error) || attempt >= attempts) throw error;
      sequenceNumber = nextConversationSequence(await input.list());
    }
  }
}

/** Finds the conversation's thread, else creates it; a create that loses a race for the (anchor-derived) id uses the winner's thread. */
export async function findOrCreateThread<Thread>(input: {
  find: () => Promise<Thread | null>;
  create: () => Promise<Thread>;
}): Promise<Thread> {
  const existing = await input.find();
  if (existing) return existing;
  try {
    return await input.create();
  } catch (error) {
    const raced = isSequenceConflict(error) ? await input.find() : null;
    if (raced) return raced;
    throw error;
  }
}
