import { createHash } from "node:crypto";
import { hashtagsInMessageText } from "../../../lib/message-hashtags";
import { conceptKeysForHashtag } from "../../../lib/wiki";

export const MESSAGE_CONCEPT_EDGE_KIND = "message.concept";
export const MESSAGE_CONCEPT_FEED_KEY = "reference-links";

export type AcceptedConceptNode = { id: string; lineageId?: string | null; versionNumber?: number | null; nodeKey: string };

export type MessageHashtagStore = {
  getMessage(messageId: string): Promise<{ id: string; content?: string | null; authorSub?: string | null; role?: string | null; status?: string | null; metadata?: unknown } | null>;
  listAcceptedConceptNodes(): Promise<AcceptedConceptNode[]>;
  getRelation(relationId: string): Promise<{ id: string; metadata?: unknown } | null>;
  putRelation(relation: Record<string, unknown>, existing: boolean): Promise<void>;
  setMessageMetadata(messageId: string, metadata: Record<string, unknown>): Promise<void>;
};

export type MessageHashtagResult = { ok: boolean; linkedNodeKeys: string[]; unmatchedHashtags: string[] };

function parseMetadata(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value || "{}");
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {};
}

export function messageConceptRelationId(messageId: string, nodeLineageId: string): string {
  const digest = createHash("sha256").update(JSON.stringify([messageId, nodeLineageId])).digest("hex").slice(0, 16);
  return `reference-link-related_to-${digest}`;
}

/**
 * Links a person's Message to the concepts it names with hashtags. Everything is read from the stored Message: the text, the author
 * and the role, so a caller cannot make an edge for words the Message does not hold or for a Message someone else wrote.
 * A hashtag that matches exactly one accepted concept becomes a current `related_to` edge, message to semanticNode, provenance
 * human. A hashtag that matches no concept, or several, is listed on the Message as `unmatchedHashtags` and creates nothing.
 */
export async function linkMessageHashtags(
  store: MessageHashtagStore,
  input: { messageId: string; callerSub: string; now: string },
): Promise<MessageHashtagResult> {
  const message = await store.getMessage(input.messageId);
  if (!message) throw new Error(`Message ${input.messageId} was not found.`);
  if (message.authorSub !== input.callerSub) throw new Error("Only the author of a Message can link its hashtags.");
  const isPerson = !message.role || message.role === "human" || message.role === "user";
  if (!isPerson || (message.status && message.status !== "active")) return { ok: true, linkedNodeKeys: [], unmatchedHashtags: [] };

  const hashtags = hashtagsInMessageText(message.content);
  const nodes = hashtags.length ? await store.listAcceptedConceptNodes() : [];
  const nodesByKey = new Map(nodes.map((node) => [node.nodeKey, node]));
  const allKeys = nodes.map((node) => node.nodeKey);
  const linkedNodeKeys: string[] = [];
  const unmatchedHashtags: string[] = [];

  for (const hashtag of hashtags) {
    const candidates = conceptKeysForHashtag(hashtag, allKeys);
    const node = candidates.length === 1 ? nodesByKey.get(candidates[0]) : undefined;
    if (!node) {
      unmatchedHashtags.push(`#${hashtag}`);
      continue;
    }
    const nodeLineageId = node.lineageId ?? node.id;
    const relationId = messageConceptRelationId(message.id, nodeLineageId);
    const existing = await store.getRelation(relationId);
    const previous = parseMetadata(existing?.metadata);
    const metadata = { ...previous, kind: MESSAGE_CONCEPT_EDGE_KIND, provenance: "human", addedBy: previous.addedBy ?? input.callerSub, addedAt: previous.addedAt ?? input.now };
    await store.putRelation(
      {
        id: relationId,
        relationState: "current",
        predicate: "related_to",
        relationTypeId: "semantic-relation-type-related-to",
        relationTypeKey: "related_to",
        relationDomain: "semantic",
        subjectKind: "message",
        subjectId: message.id,
        subjectLineageId: message.id,
        subjectVersionNumber: 1,
        objectKind: "semanticNode",
        objectId: node.id,
        objectLineageId: nodeLineageId,
        objectVersionNumber: node.versionNumber ?? null,
        subjectStateKey: `message#${message.id}#current`,
        objectStateKey: `semanticNode#${nodeLineageId}#current`,
        objectSubjectStateKey: `semanticNode#${nodeLineageId}#current#message`,
        predicateObjectStateKey: `related_to#semanticNode#${nodeLineageId}#current`,
        subjectVersionKey: `message#${message.id}`,
        objectVersionKey: `semanticNode#${node.id}`,
        rank: 1,
        reviewRecommended: false,
        importedAt: input.now,
        updatedAt: input.now,
        newsroomFeedKey: MESSAGE_CONCEPT_FEED_KEY,
        metadata: JSON.stringify(metadata),
      },
      existing !== null,
    );
    linkedNodeKeys.push(node.nodeKey);
  }

  const messageMetadata = parseMetadata(message.metadata);
  if (unmatchedHashtags.length || "unmatchedHashtags" in messageMetadata) {
    if (unmatchedHashtags.length) messageMetadata.unmatchedHashtags = unmatchedHashtags;
    else delete messageMetadata.unmatchedHashtags;
    await store.setMessageMetadata(message.id, messageMetadata);
  }
  return { ok: true, linkedNodeKeys, unmatchedHashtags };
}
