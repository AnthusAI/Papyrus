import { createHash } from "node:crypto";

export const REFERENCE_LINK_KIND = "reference.link";
export const REFERENCE_CONCEPT_KIND = "reference.concept";
export const ITEM_CONCEPT_KIND = "item.concept";
export const REFERENCE_LINK_FEED_KEY = "reference-links";
export const RELATED_TO = "related_to";
export const REFERENCE_LINK_PREDICATES = ["related_to", "cites", "supports", "contradicts"] as const;
export const SYMMETRIC_PREDICATES: readonly string[] = [RELATED_TO];
export const LINK_DECISIONS = { accept: "accepted", reject: "rejected" } as const;
const DECIDABLE_KINDS: readonly string[] = [REFERENCE_LINK_KIND, REFERENCE_CONCEPT_KIND, ITEM_CONCEPT_KIND];
const STATE_FOR_DECISION = { accepted: "current", rejected: "rejected" } as const;

const RELATION_TYPE_FIELDS: Record<string, { relationTypeId: string; relationTypeKey: string; relationDomain: string }> = {
  related_to: { relationTypeId: "semantic-relation-type-related-to", relationTypeKey: "related_to", relationDomain: "generic" },
  cites: { relationTypeId: "semantic-relation-type-cites", relationTypeKey: "cites", relationDomain: "evidence" },
  supports: { relationTypeId: "semantic-relation-type-supports", relationTypeKey: "supports", relationDomain: "evidence" },
  contradicts: { relationTypeId: "semantic-relation-type-contradicts", relationTypeKey: "contradicts", relationDomain: "evidence" },
};

export type ReferenceLinkPredicate = (typeof REFERENCE_LINK_PREDICATES)[number];
export type ReferenceLinkDecision = keyof typeof LINK_DECISIONS;
export type ReferenceRecord = { id: string; lineageId?: string | null; versionNumber?: number | null };
export type SemanticNodeRecord = { id: string; lineageId?: string | null; versionNumber?: number | null };
export type ReferenceLinkRow = Record<string, unknown> & {
  id: string;
  relationState?: string | null;
  predicate?: string | null;
  subjectKind?: string | null;
  subjectLineageId?: string | null;
  objectKind?: string | null;
  objectLineageId?: string | null;
  metadata?: unknown;
};

export type ReferenceLinkStore = {
  getCurrentReference(referenceIdOrLineageId: string): Promise<ReferenceRecord | null>;
  getSemanticNode(lineageId: string): Promise<SemanticNodeRecord | null>;
  getRelation(relationId: string): Promise<ReferenceLinkRow | null>;
  putRelation(relation: Record<string, unknown>, existing: boolean): Promise<void>;
};

export type ReferenceLinkResult = { ok: boolean; relationId: string; relationState: string; outcome: string | null; decision: string | null };

type Edge = { kind: string; id: string; lineageId: string; versionNumber: number | null };

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

function pythonCompatibleJson(value: unknown): string {
  return JSON.stringify(value).replace(/[\u007f-￿]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

export function hashShort(value: unknown): string {
  return createHash("sha256").update(pythonCompatibleJson(value)).digest("hex").slice(0, 16);
}

export function referenceLinkRelationId(predicate: string, firstLineageId: string, secondLineageId: string): string {
  return `reference-link-${predicate}-${hashShort([firstLineageId, secondLineageId])}`;
}

export function referenceLinkStateKeys(subject: Edge, object: Edge, predicate: string, state: string) {
  return referenceLinkStateKeysFromParts(subject.kind, subject.lineageId, object.kind, object.lineageId, predicate, state);
}

function referenceLinkStateKeysFromParts(subjectKind: string, subjectLineageId: string, objectKind: string, objectLineageId: string, predicate: string, state: string) {
  const objectStateKey = `${objectKind}#${objectLineageId}#${state}`;
  return {
    subjectStateKey: `${subjectKind}#${subjectLineageId}#${state}`,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#${subjectKind}`,
    predicateObjectStateKey: `${predicate}#${objectStateKey}`,
  };
}

function referenceEdge(reference: ReferenceRecord, requestedId: string): Edge {
  return { kind: "reference", id: reference.id, lineageId: reference.lineageId ?? requestedId, versionNumber: reference.versionNumber ?? null };
}

function optionalText(value: string | null | undefined): string | null {
  const trimmed = (value ?? "").trim();
  return trimmed === "" ? null : trimmed;
}

/** The row a person's confirmed link is written as: the same fields, state keys and metadata keys as the Python writer in src/papyrus_content/reference_links.py. */
export function buildHumanEdgeRow(input: { relationId: string; kind: string; predicate: string; subject: Edge; object: Edge; existing: ReferenceLinkRow | null; actor: string; note: string | null; now: string }): Record<string, unknown> {
  const previous = parseMetadata(input.existing?.metadata);
  const metadata: Record<string, unknown> = {
    ...previous,
    kind: input.kind,
    provenance: "human",
    suggestedBy: previous.suggestedBy ?? null,
    addedBy: previous.addedBy || input.actor,
    addedAt: previous.addedAt || input.now,
    decidedBy: previous.decidedBy ?? null,
    decidedAt: previous.decidedAt ?? null,
    decision: previous.decision ?? null,
    reasonCode: previous.reasonCode ?? null,
    note: input.note || previous.note || null,
  };
  if (!previous.decision) Object.assign(metadata, { decidedBy: input.actor, decidedAt: input.now, decision: "accepted" });
  return {
    id: input.relationId,
    relationState: "current",
    predicate: input.predicate,
    ...RELATION_TYPE_FIELDS[input.predicate],
    subjectKind: input.subject.kind,
    subjectId: input.subject.id,
    subjectLineageId: input.subject.lineageId,
    subjectVersionNumber: input.subject.versionNumber,
    objectKind: input.object.kind,
    objectId: input.object.id,
    objectLineageId: input.object.lineageId,
    objectVersionNumber: input.object.versionNumber,
    ...referenceLinkStateKeys(input.subject, input.object, input.predicate, "current"),
    subjectVersionKey: `${input.subject.kind}#${input.subject.id}`,
    objectVersionKey: `${input.object.kind}#${input.object.id}`,
    score: null,
    confidence: null,
    rank: 1,
    classifierId: null,
    modelVersion: null,
    reviewRecommended: false,
    importedAt: input.now,
    updatedAt: input.now,
    newsroomFeedKey: REFERENCE_LINK_FEED_KEY,
    metadata: JSON.stringify(metadata),
  };
}

/**
 * Writes a current link a signed-in editor makes: from a Reference (by lineage id) to another Reference or to a concept
 * (`semanticNode`), provenance human, addedBy and decidedBy taken from the caller. `related_to` between two References is one
 * row with the lower lineage id as subject; the other predicates point from the first Reference to the second. Writing the
 * same pair again updates the one row.
 */
export async function createReferenceLink(
  store: ReferenceLinkStore,
  input: { subjectLineageId: string; objectKind: string; objectLineageId: string; predicate: string; note?: string | null; callerSub: string; now: string },
): Promise<ReferenceLinkResult> {
  if (!(REFERENCE_LINK_PREDICATES as readonly string[]).includes(input.predicate)) {
    throw new Error(`predicate must be one of ${REFERENCE_LINK_PREDICATES.join(", ")}.`);
  }
  if (input.objectKind !== "reference" && input.objectKind !== "semanticNode") throw new Error("objectKind must be reference or semanticNode.");
  const subjectReference = await store.getCurrentReference(input.subjectLineageId);
  if (!subjectReference) throw new Error(`Reference not found: ${input.subjectLineageId}`);
  let first = referenceEdge(subjectReference, input.subjectLineageId);
  let second: Edge;
  let kind: string;
  if (input.objectKind === "reference") {
    const objectReference = await store.getCurrentReference(input.objectLineageId);
    if (!objectReference) throw new Error(`Reference not found: ${input.objectLineageId}`);
    second = referenceEdge(objectReference, input.objectLineageId);
    if (first.lineageId === second.lineageId) throw new Error("A reference cannot be linked to itself.");
    if (SYMMETRIC_PREDICATES.includes(input.predicate) && second.lineageId < first.lineageId) [first, second] = [second, first];
    kind = REFERENCE_LINK_KIND;
  } else {
    if (input.predicate !== RELATED_TO) throw new Error("A concept is linked with the related_to predicate.");
    const node = await store.getSemanticNode(input.objectLineageId);
    if (!node) throw new Error(`Concept not found: ${input.objectLineageId}`);
    second = { kind: "semanticNode", id: node.id, lineageId: node.lineageId ?? node.id, versionNumber: node.versionNumber ?? null };
    kind = REFERENCE_CONCEPT_KIND;
  }
  const relationId = referenceLinkRelationId(input.predicate, first.lineageId, second.lineageId);
  const existing = await store.getRelation(relationId);
  const row = buildHumanEdgeRow({ relationId, kind, predicate: input.predicate, subject: first, object: second, existing, actor: input.callerSub, note: optionalText(input.note), now: input.now });
  await store.putRelation(row, existing !== null);
  return { ok: true, relationId, relationState: "current", outcome: existing ? "updated" : "created", decision: null };
}

/**
 * Records an editor's accept or reject of a link: the new state, its state keys, and who decided, when and why (reasonCode and
 * note are optional). The decision comes from the caller's identity and only a reference or concept link can be decided.
 */
export async function decideReferenceLink(
  store: ReferenceLinkStore,
  input: { relationId: string; decision: string; reasonCode?: string | null; note?: string | null; callerSub: string; now: string },
): Promise<ReferenceLinkResult> {
  if (input.decision !== "accept" && input.decision !== "reject") throw new Error("decision must be accept or reject.");
  const row = await store.getRelation(input.relationId);
  if (!row) throw new Error(`Reference link not found: ${input.relationId}`);
  const previous = parseMetadata(row.metadata);
  if (!DECIDABLE_KINDS.includes(String(previous.kind))) throw new Error(`${input.relationId} is not a reference link.`);
  const decision = LINK_DECISIONS[input.decision];
  const state = STATE_FOR_DECISION[decision];
  const metadata = {
    ...previous,
    decidedBy: input.callerSub,
    decidedAt: input.now,
    decision,
    reasonCode: optionalText(input.reasonCode),
    note: optionalText(input.note),
  };
  await store.putRelation(
    {
      id: input.relationId,
      relationState: state,
      ...referenceLinkStateKeysFromParts(String(row.subjectKind), String(row.subjectLineageId), String(row.objectKind), String(row.objectLineageId), String(row.predicate), state),
      reviewRecommended: false,
      updatedAt: input.now,
      metadata: JSON.stringify(metadata),
    },
    true,
  );
  return { ok: true, relationId: input.relationId, relationState: state, outcome: null, decision };
}
