import { createHash } from "node:crypto";
import { changeReasonAfterNewDescription } from "./knowledge-review";
import { REFERENCE_LINK_FEED_KEY, SEMANTIC_NODE_FEED_KEY, globalKey } from "../../../lib/tenant-knowledge-keys";
import { currentTenantContext } from "../shared/tenant-context";

export const REFERENCE_LINK_KIND = "reference.link";
export const REFERENCE_CONCEPT_KIND = "reference.concept";
export const ITEM_CONCEPT_KIND = "item.concept";
/** A link an editor makes between two concepts, with the words that say how they relate. The same row as a Reference link: related_to, metadata note. */
export const CONCEPT_LINK_KIND = "concept.link";
export { REFERENCE_LINK_FEED_KEY };
export const RELATED_TO = "related_to";
/** Tagging a Reference or a story with a concept (renamed from `related_to` on 2026-11-09; stored `related_to` tag rows are read until `papyrus relations migrate-concept-tags` has run). */
export const TAGGED_WITH = "tagged_with";
export const REFERENCE_LINK_PREDICATES = ["related_to", "cites", "supports", "contradicts"] as const;
export const SYMMETRIC_PREDICATES: readonly string[] = [RELATED_TO];
export const LINK_DECISIONS = { accept: "accepted", reject: "rejected" } as const;
const DECIDABLE_KINDS: readonly string[] = [REFERENCE_LINK_KIND, REFERENCE_CONCEPT_KIND, ITEM_CONCEPT_KIND, CONCEPT_LINK_KIND];
const STATE_FOR_DECISION = { accepted: "current", rejected: "rejected" } as const;

const RELATION_TYPE_FIELDS: Record<string, { relationTypeId: string; relationTypeKey: string; relationDomain: string }> = {
  related_to: { relationTypeId: "semantic-relation-type-related-to", relationTypeKey: "related_to", relationDomain: "generic" },
  tagged_with: { relationTypeId: "semantic-relation-type-tagged-with", relationTypeKey: "tagged_with", relationDomain: "editorial" },
  cites: { relationTypeId: "semantic-relation-type-cites", relationTypeKey: "cites", relationDomain: "evidence" },
  supports: { relationTypeId: "semantic-relation-type-supports", relationTypeKey: "supports", relationDomain: "evidence" },
  contradicts: { relationTypeId: "semantic-relation-type-contradicts", relationTypeKey: "contradicts", relationDomain: "evidence" },
};

export type ReferenceLinkPredicate = (typeof REFERENCE_LINK_PREDICATES)[number];
export type ReferenceLinkDecision = keyof typeof LINK_DECISIONS;
export type ReferenceRecord = { id: string; lineageId?: string | null; versionNumber?: number | null };
export type SemanticNodeRecord = { id: string; lineageId?: string | null; versionNumber?: number | null; nodeKey?: string | null; nodeKind?: string | null; description?: string | null; status?: string | null; changeReason?: string | null };

/** The kind of a concept an editor invented by typing its hashtag. The public wiki and the concept cards know it (src/papyrus_content/knowledge_wiki/kinds.py). */
export const EDITOR_CONCEPT_KIND = "editor_concept";

/** `#Fake Website  Networks` -> `fake-website-networks`: the name part of the key `conceptKeysForHashtag` matches (lower case, runs of other characters one hyphen). */
export function conceptSlug(text: string): string {
  return text.trim().replace(/^#+/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
}

export function editorConceptKey(slug: string): string {
  return `${EDITOR_CONCEPT_KIND}--${slug}`;
}

/** The lineage id of the concept, the same for anyone who types the same name: the id is the node's key (`semantic-node-<key>`), so two taps make one node. */
export function editorConceptLineageId(slug: string): string {
  return `semantic-node-${editorConceptKey(slug)}`;
}
const MAXIMUM_DISPLAY_NAME_LENGTH = 120;

/**
 * The name a person typed for a concept, kept as they typed it ("Information flow control", "Non-interference"): white space collapsed, a leading
 * `#` dropped. It must be the same words as the concept's key, so the name cannot drift from the key it is found by.
 */
export function editorConceptDisplayName(typed: string, slug: string): string {
  const name = typed.trim().replace(/^#+/, "").replace(/\s+/g, " ").trim();
  if (!name) throw new Error("A concept needs a name.");
  if (name.length > MAXIMUM_DISPLAY_NAME_LENGTH) throw new Error(`A concept name is at most ${MAXIMUM_DISPLAY_NAME_LENGTH} characters.`);
  if (conceptSlug(name) !== slug) throw new Error(`The name "${name}" is not the same words as the concept's key (${slug}).`);
  return name;
}

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
  /** Creates a SemanticNode with this exact record; false when one with its id already exists (a second tap, or someone else made it first). */
  createSemanticNode?(node: Record<string, unknown>): Promise<boolean>;
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
export function buildHumanEdgeRow(input: { relationId: string; kind: string; predicate: string; subject: Edge; object: Edge; existing: ReferenceLinkRow | null; actor: string; note: string | null; now: string; origin?: string | null }): Record<string, unknown> {
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
  // Where the link was made and where it was decided (editOriginOf): a link made from the CLI does not read as one made in the Newsroom. A row from
  // before this has neither, which reads as unknown.
  if (input.origin) {
    if (!previous.addedVia) metadata.addedVia = input.origin;
    if (!previous.decision) metadata.decidedVia = input.origin;
  }
  // A person made a link between two concepts, so it is a confirmed relation between them for the readers of concept relations (`confirmed`).
  if (input.kind === CONCEPT_LINK_KIND) metadata.confirmed = true;
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
    // score sorts two indexes on this model, and DynamoDB refuses a null index key. A person's link is certain, so it is the top of the scale.
    score: 1,
    confidence: null,
    rank: 1,
    classifierId: null,
    modelVersion: null,
    reviewRecommended: false,
    importedAt: input.now,
    updatedAt: input.now,
    newsroomFeedKey: globalKey(REFERENCE_LINK_FEED_KEY, currentTenantContext().tenantId),
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
  input: { subjectLineageId: string; objectKind: string; objectLineageId: string; predicate: string; note?: string | null; newConceptName?: string | null; newConceptDisplayName?: string | null; callerSub: string; now: string; origin?: string | null },
): Promise<ReferenceLinkResult> {
  if (!(REFERENCE_LINK_PREDICATES as readonly string[]).includes(input.predicate) && input.predicate !== TAGGED_WITH) {
    throw new Error(`predicate must be one of ${REFERENCE_LINK_PREDICATES.join(", ")}.`);
  }
  if (input.objectKind !== "reference" && input.objectKind !== "semanticNode") throw new Error("objectKind must be reference or semanticNode.");
  const subjectReference = await store.getCurrentReference(input.subjectLineageId);
  if (!subjectReference) throw new Error(`Reference not found: ${input.subjectLineageId}`);
  let predicate = input.predicate;
  let first = referenceEdge(subjectReference, input.subjectLineageId);
  let second: Edge;
  let kind: string;
  if (input.objectKind === "reference") {
    const objectReference = await store.getCurrentReference(input.objectLineageId);
    if (!objectReference) throw new Error(`Reference not found: ${input.objectLineageId}`);
    second = referenceEdge(objectReference, input.objectLineageId);
    if (first.lineageId === second.lineageId) throw new Error("A reference cannot be linked to itself.");
    if (predicate === TAGGED_WITH) throw new Error("tagged_with tags a Reference with a concept; between two References use related_to, cites, supports or contradicts.");
    if (SYMMETRIC_PREDICATES.includes(predicate) && second.lineageId < first.lineageId) [first, second] = [second, first];
    kind = REFERENCE_LINK_KIND;
  } else {
    // A Reference is tagged with a concept with `tagged_with`; a client that still sends `related_to` for it means the same, and the row is written as `tagged_with`.
    if (input.predicate !== TAGGED_WITH && input.predicate !== RELATED_TO) throw new Error("A concept is linked with the tagged_with predicate.");
    predicate = TAGGED_WITH;
    const node = input.newConceptName ? await ensureEditorConcept(store, input.newConceptName, input.callerSub, input.now, { displayName: input.newConceptDisplayName, origin: input.origin }) : await store.getSemanticNode(input.objectLineageId);
    if (!node) throw new Error(`Concept not found: ${input.objectLineageId}`);
    second = { kind: "semanticNode", id: node.id, lineageId: node.lineageId ?? node.id, versionNumber: node.versionNumber ?? null };
    kind = REFERENCE_CONCEPT_KIND;
  }
  let relationId = referenceLinkRelationId(predicate, first.lineageId, second.lineageId);
  let existing = await store.getRelation(relationId);
  if (kind === REFERENCE_CONCEPT_KIND && !existing) {
    // The same pair under the old name, not migrated yet: update that row in place rather than write a second row beside it (the migration moves it later).
    const legacyId = referenceLinkRelationId(RELATED_TO, first.lineageId, second.lineageId);
    const legacy = await store.getRelation(legacyId);
    if (legacy && legacy.relationState !== "superseded") {
      relationId = legacyId;
      existing = legacy;
      predicate = RELATED_TO;
    }
  }
  const row = buildHumanEdgeRow({ relationId, kind, predicate, subject: first, object: second, existing, actor: input.callerSub, note: optionalText(input.note), now: input.now, origin: input.origin });
  await store.putRelation(row, existing !== null);
  return { ok: true, relationId, relationState: "current", outcome: existing ? "updated" : "created", decision: null };
}

/**
 * Writes a current link a signed-in editor makes between two concepts (`semanticNode` to `semanticNode`), related_to, with the words that say how they
 * relate: the same row, state keys and metadata as a Reference link, kind `concept.link`, so the readers of an editor's explanation (the internal
 * knowledge query, the section context packs) read it as they read the others. The explanation is required: a link between two concepts that says
 * nothing about how they relate is not the meaning an editor is adding. related_to is symmetric, so one row with the lower lineage id as subject;
 * writing the same pair again updates that row, and the new words replace the earlier ones.
 */
export async function createConceptLink(
  store: ReferenceLinkStore,
  input: { subjectLineageId: string; objectLineageId: string; note: string | null | undefined; callerSub: string; now: string; origin?: string | null },
): Promise<ReferenceLinkResult> {
  const note = optionalText(input.note);
  if (!note) throw new Error("Say how the two concepts relate: a link between concepts needs its explanation.");
  const [subjectNode, objectNode] = await Promise.all([store.getSemanticNode(input.subjectLineageId), store.getSemanticNode(input.objectLineageId)]);
  if (!subjectNode) throw new Error(`Concept not found: ${input.subjectLineageId}`);
  if (!objectNode) throw new Error(`Concept not found: ${input.objectLineageId}`);
  for (const node of [subjectNode, objectNode]) {
    if ((node as { status?: string | null }).status === "rejected") throw new Error(`The concept ${node.nodeKey ?? node.id} was rejected, so it cannot be linked.`);
  }
  const edgeOf = (node: SemanticNodeRecord): Edge => ({ kind: "semanticNode", id: node.id, lineageId: node.lineageId ?? node.id, versionNumber: node.versionNumber ?? null });
  let first = edgeOf(subjectNode);
  let second = edgeOf(objectNode);
  if (first.lineageId === second.lineageId) throw new Error("A concept cannot be linked to itself.");
  if (second.lineageId < first.lineageId) [first, second] = [second, first];
  const relationId = referenceLinkRelationId(RELATED_TO, first.lineageId, second.lineageId);
  const existing = await store.getRelation(relationId);
  const row = buildHumanEdgeRow({ relationId, kind: CONCEPT_LINK_KIND, predicate: RELATED_TO, subject: first, object: second, existing, actor: input.callerSub, note, now: input.now, origin: input.origin });
  row.metadata = JSON.stringify({ ...parseMetadata(row.metadata), note });
  await store.putRelation(row, existing !== null);
  return { ok: true, relationId, relationState: "current", outcome: existing ? "updated" : "created", decision: null };
}

/**
 * The concept an editor invents by typing its hashtag: found if it exists (a double tap, or the name was made before), made if not. No dialog and no
 * required fields: the node has the name, the kind `editor_concept`, status accepted, who made it and when, and no description (an editor adds one on the
 * concept's page later). Nothing publishes it: the public wiki publishes only the kinds the site's vocabulary names.
 */
export async function ensureEditorConcept(store: ReferenceLinkStore, name: string, callerSub: string, now: string, options: { displayName?: string | null; origin?: string | null } = {}): Promise<SemanticNodeRecord> {
  const slug = conceptSlug(name);
  if (!slug) throw new Error("A concept needs a name.");
  // The name the person typed, if they gave one; else the key's words with spaces (the name a hashtag has always made).
  const displayName = optionalText(options.displayName) ? editorConceptDisplayName(options.displayName as string, slug) : slug.replace(/-/g, " ");
  const lineageId = editorConceptLineageId(slug);
  const existing = await store.getSemanticNode(lineageId);
  if (existing) return existing;
  if (!store.createSemanticNode) throw new Error("This backend cannot create concepts.");
  const node = {
    id: `${lineageId}-v1`, lineageId, versionNumber: 1, versionState: "current", versionCreatedAt: now, versionCreatedBy: callerSub, changeReason: options.origin && options.origin !== "newsroom" ? `Invented by an editor with a hashtag (via ${options.origin})` : "Invented by an editor with a hashtag",
    nodeKey: editorConceptKey(slug), nodeKind: EDITOR_CONCEPT_KIND, displayName, status: "accepted", aliases: [], createdAt: now, updatedAt: now,
    newsroomFeedKey: globalKey(SEMANTIC_NODE_FEED_KEY, currentTenantContext().tenantId),
  };
  await store.createSemanticNode(node);   // false: it exists now (a second tap); read it back either way
  const made = await store.getSemanticNode(lineageId);
  if (!made) throw new Error(`The concept could not be created: ${lineageId}`);
  return made;
}

/** An editor's description of an editor-made concept. Concepts the knowledge runs generate are not edited here (the next run would replace the words). */
export async function describeEditorConcept(
  store: ReferenceLinkStore & { updateSemanticNode?(node: Record<string, unknown>): Promise<void> },
  input: { lineageId: string; description: string | null; callerSub: string; now: string; origin?: string | null },
): Promise<{ ok: boolean; lineageId: string; description: string | null }> {
  const node = await store.getSemanticNode(input.lineageId);
  if (!node) throw new Error(`Concept not found: ${input.lineageId}`);
  if (node.nodeKind !== EDITOR_CONCEPT_KIND) throw new Error("Only a concept an editor made can be described here.");
  if (!store.updateSemanticNode) throw new Error("This backend cannot update concepts.");
  const description = optionalText(input.description);
  await store.updateSemanticNode({ id: node.id, description, versionCreatedBy: input.callerSub, changeReason: changeReasonAfterNewDescription(node.changeReason, input.origin && input.origin !== "newsroom" ? `Described by an editor (via ${input.origin})` : "Described by an editor"), updatedAt: input.now });
  return { ok: true, lineageId: node.lineageId ?? node.id, description };
}

/**
 * Records an editor's accept or reject of a link: the new state, its state keys, and who decided, when and why (reasonCode and
 * note are optional). The decision comes from the caller's identity and only a reference or concept link can be decided.
 */
export async function decideReferenceLink(
  store: ReferenceLinkStore,
  input: { relationId: string; decision: string; reasonCode?: string | null; note?: string | null; callerSub: string; now: string; origin?: string | null },
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
    ...(input.origin ? { decidedVia: input.origin } : {}),
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
