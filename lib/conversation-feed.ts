/**
 * The Messages page: which MessageThreads are conversations, which section each belongs to, and how several newest-first streams
 * (one per thread kind) merge into one page of conversations ordered by last activity. Pure helpers, shared by the browser and the tests.
 */
import { GENERAL_CONVERSATION_KIND, REFERENCE_CONVERSATION_KIND, STORY_CONVERSATION_KIND } from "./conversation";

export type ConversationSection = "all" | "references" | "stories" | "chats" | "other";
export const CONVERSATION_SECTIONS: ReadonlyArray<{ key: ConversationSection; label: string }> = [
  { key: "all", label: "All" },
  { key: "references", label: "References" },
  { key: "stories", label: "Stories" },
  { key: "chats", label: "Chats" },
  { key: "other", label: "Other" },
];

export const CHAT_THREAD_KIND = "console";
export const FORUM_THREAD_KINDS = ["edition_forum", "section_forum"] as const;

/** The thread kinds that are conversations, by section. Machine records (provenance, curation, ingestion rationale) are in none of them. */
const KINDS_BY_SECTION: Record<Exclude<ConversationSection, "all">, ReadonlyArray<string>> = {
  references: [REFERENCE_CONVERSATION_KIND],
  stories: [STORY_CONVERSATION_KIND],
  chats: [CHAT_THREAD_KIND],
  other: [GENERAL_CONVERSATION_KIND, ...FORUM_THREAD_KINDS],
};

export function threadKindsForSection(section: ConversationSection): string[] {
  if (section === "all") return Object.values(KINDS_BY_SECTION).flat();
  return [...KINDS_BY_SECTION[section]];
}

/** The section a thread kind is listed under, or null for a kind that is not a conversation. */
export function sectionOfThreadKind(kind: string): Exclude<ConversationSection, "all"> | null {
  for (const [section, kinds] of Object.entries(KINDS_BY_SECTION)) if (kinds.includes(kind)) return section as Exclude<ConversationSection, "all">;
  return null;
}

export const SECTION_EMPTY_COPY: Record<ConversationSection, string> = {
  all: "No conversations yet. Write a message above, or on a Reference, to start one.",
  references: "No Reference has a message yet. Open a Reference and write down what it made you think.",
  stories: "No Story has a message yet.",
  chats: "No chats yet.",
  other: "No other conversations yet. Write a message above to start one.",
};

export type PagedThreads<Thread> = { items: Thread[]; nextToken: string | null };

type Streamable = { id: string; updatedAt: string };

/**
 * One page at a time out of several newest-first streams, merged by `updatedAt` (the order of every thread index). A stream is only
 * asked for another page when its buffered threads have all been shown, so the order across streams is exact, never approximate.
 */
export function createMergedThreadStream<Thread extends Streamable>(
  kinds: ReadonlyArray<string>,
  loadPage: (kind: string, nextToken: string | null) => Promise<PagedThreads<Thread>>,
) {
  const lanes = kinds.map((kind) => ({ kind, buffer: [] as Thread[], nextToken: null as string | null, started: false, done: false }));
  const seen = new Set<string>();

  async function fill() {
    await Promise.all(lanes.filter((lane) => !lane.done && lane.buffer.length === 0).map(async (lane) => {
      const page = await loadPage(lane.kind, lane.started ? lane.nextToken : null);
      lane.started = true;
      lane.nextToken = page.nextToken;
      lane.done = !page.nextToken;
      lane.buffer = [...page.items].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
    }));
  }

  return {
    /** The next `count` conversations, newest first, and whether more remain. */
    async next(count: number): Promise<{ items: Thread[]; hasMore: boolean }> {
      const items: Thread[] = [];
      while (items.length < count) {
        await fill();
        const live = lanes.filter((lane) => lane.buffer.length > 0);
        if (!live.length) break;
        // A lane that is not finished and has an empty buffer after a fill returned an empty page with more behind it: ask again.
        if (lanes.some((lane) => !lane.done && lane.buffer.length === 0)) continue;
        const best = live.reduce((winner, lane) => (lane.buffer[0].updatedAt.localeCompare(winner.buffer[0].updatedAt) > 0 ? lane : winner));
        const thread = best.buffer.shift()!;
        if (seen.has(thread.id)) continue;
        seen.add(thread.id);
        items.push(thread);
      }
      return { items, hasMore: lanes.some((lane) => lane.buffer.length > 0 || !lane.done) };
    },
  };
}

/** The newest `limit` messages, oldest first, and how many are held back behind "Show all". */
export function latestMessages<Message>(messages: ReadonlyArray<Message>, limit: number, showAll: boolean): { shown: Message[]; hidden: number } {
  if (showAll || messages.length <= limit) return { shown: [...messages], hidden: 0 };
  return { shown: messages.slice(messages.length - limit), hidden: messages.length - limit };
}
