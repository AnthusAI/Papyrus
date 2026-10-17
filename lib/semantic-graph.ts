import { toPublicNewsroomPath } from "./newsroom-base-path";
import type {
  AssignmentRecord,
  CategorySteeringCategory,
  MessageRecord,
  NewsroomSectionRecord,
  ReferenceAttachmentRecord,
  ReferenceRecord,
  SemanticNodeRecord,
  SemanticRelationRecord,
} from "./category-repository";
import { isEvidenceEligibleReference } from "./reference-policy";

export const SEMANTIC_OBJECT_KINDS = [
  "reference",
  "assignment",
  "item",
  "category",
  "categorySet",
  "semanticNode",
  "semanticRelation",
  "message",
  "steeringProposal",
  "steeringDecision",
  "knowledgeArtifact",
  "knowledgeImportRun",
  "newsroomSection",
] as const;

export type SemanticObjectKind = typeof SEMANTIC_OBJECT_KINDS[number];

export type SemanticPredicateId =
  | "classified_as"
  | "quality_rating_is"
  | "relevance_decision_is"
  | "reference_summary_100_tokens"
  | "reference_summary_200_tokens"
  | "reference_summary_500_tokens"
  | "reference_summary_1000_tokens"
  | "mentions"
  | "has_editorial_form"
  | "about"
  | "comment"
  | "insight_about"
  | "ingestion_rationale"
  | "uses_evidence"
  | "uses_signal"
  | "requests_work_on"
  | "planned_for_edition"
  | "targets_lane"
  | "targets_section"
  | "targets_topic"
  | "scoped_to_topic"
  | "produces"
  | "blocked_by"
  | "derived_from"
  | "related_to"
  | "broader_than"
  | "narrower_than"
  | "supports"
  | "contradicts";

export type SemanticPredicateDefinition = {
  id: SemanticPredicateId | string;
  label: string;
  group: "knowledge" | "editorial" | "workflow" | "evidence" | "ontology" | "commentary" | "publication" | "generic" | "classification" | "curation" | "summarization";
  inverseLabel: string;
  contextPackTags?: string[];
};

export const SEMANTIC_PREDICATES: SemanticPredicateDefinition[] = [
  { id: "classified_as", label: "classified as", group: "knowledge", inverseLabel: "classified references/items", contextPackTags: ["reference_graph", "research", "category_context"] },
  { id: "quality_rating_is", label: "quality rating is", group: "curation", inverseLabel: "quality rating for", contextPackTags: ["reference_curation", "research", "context_ranking"] },
  { id: "reference_summary_100_tokens", label: "100-token reference summary", group: "summarization", inverseLabel: "100-token summary for", contextPackTags: ["reference_curation", "research", "context_ranking"] },
  { id: "reference_summary_200_tokens", label: "200-token reference summary", group: "summarization", inverseLabel: "200-token summary for", contextPackTags: ["reference_curation", "research", "context_ranking"] },
  { id: "reference_summary_500_tokens", label: "500-token reference summary", group: "summarization", inverseLabel: "500-token summary for", contextPackTags: ["reference_curation", "research", "context_ranking"] },
  { id: "reference_summary_1000_tokens", label: "1000-token reference summary", group: "summarization", inverseLabel: "1000-token summary for", contextPackTags: ["reference_curation", "research", "context_ranking"] },
  { id: "mentions", label: "mentions", group: "ontology", inverseLabel: "mentioned by" },
  { id: "has_editorial_form", label: "has editorial form", group: "editorial", inverseLabel: "items by editorial form", contextPackTags: ["editing", "publication", "assignment_context"] },
  { id: "insight_about", label: "insight about", group: "knowledge", inverseLabel: "insights", contextPackTags: ["research", "reference_graph", "editing"] },
  { id: "about", label: "about", group: "commentary", inverseLabel: "commentary" },
  { id: "comment", label: "comments on", group: "commentary", inverseLabel: "commented on by", contextPackTags: ["reference_curation", "editing", "research", "assignment_context"] },
  { id: "ingestion_rationale", label: "ingestion rationale for", group: "commentary", inverseLabel: "ingestion rationale", contextPackTags: ["reference_curation", "editing", "research", "assignment_context"] },
  { id: "relevance_decision_is", label: "relevance decision is", group: "workflow", inverseLabel: "relevance decision for", contextPackTags: ["reference_curation"] },
  { id: "requests_work_on", label: "requests work on", group: "workflow", inverseLabel: "requested work", contextPackTags: ["assignment_context", "editing"] },
  { id: "uses_evidence", label: "uses evidence", group: "evidence", inverseLabel: "used as evidence by", contextPackTags: ["assignment_context", "research", "reference_graph"] },
  { id: "uses_signal", label: "uses signal", group: "evidence", inverseLabel: "signal for", contextPackTags: ["assignment_context", "research", "reference_graph"] },
  { id: "planned_for_edition", label: "planned for edition", group: "publication", inverseLabel: "planned assignments", contextPackTags: ["assignment_context", "editing", "publication"] },
  { id: "targets_lane", label: "targets lane", group: "editorial", inverseLabel: "lane targets", contextPackTags: ["assignment_context", "editing", "publication"] },
  { id: "targets_section", label: "targets section", group: "editorial", inverseLabel: "section assignments", contextPackTags: ["assignment_context", "editing", "publication"] },
  { id: "targets_topic", label: "targets topic", group: "editorial", inverseLabel: "topic assignments", contextPackTags: ["assignment_context", "editing", "publication", "research"] },
  { id: "scoped_to_topic", label: "scoped to topic", group: "ontology", inverseLabel: "semantic concepts scoped here", contextPackTags: ["assignment_context", "research", "reference_graph", "category_context"] },
  { id: "produces", label: "produces", group: "workflow", inverseLabel: "produced by" },
  { id: "blocked_by", label: "blocked by", group: "workflow", inverseLabel: "blocks" },
  { id: "derived_from", label: "derived from", group: "evidence", inverseLabel: "source for" },
  { id: "related_to", label: "related to", group: "generic", inverseLabel: "related from" },
  { id: "broader_than", label: "broader than", group: "ontology", inverseLabel: "narrower concept" },
  { id: "narrower_than", label: "narrower than", group: "ontology", inverseLabel: "broader concept" },
  { id: "supports", label: "supports", group: "evidence", inverseLabel: "supported by" },
  { id: "contradicts", label: "contradicts", group: "evidence", inverseLabel: "contradicted by" },
];

export type SemanticObjectRecord =
  | ReferenceRecord
  | CategorySteeringCategory
  | SemanticNodeRecord
  | MessageRecord
  | NewsroomSectionRecord
  | AssignmentRecord
  | SemanticRelationRecord;

export type SemanticObjectSummary = {
  kind: SemanticObjectKind;
  id: string;
  lineageId: string;
  versionNumber?: number | null;
  label: string;
  subtitle?: string | null;
  href: string;
  record?: SemanticObjectRecord;
};

export type SemanticNeighborGroup = {
  predicate: string;
  label: string;
  direction: "outgoing" | "incoming";
  relations: SemanticRelationRecord[];
  objects: SemanticObjectSummary[];
};

export type SemanticWalkResult = {
  start: SemanticObjectSummary | null;
  nodes: SemanticObjectSummary[];
  edges: SemanticRelationRecord[];
  warnings: string[];
};

export type SemanticGraphSnapshotInput = {
  references: ReferenceRecord[];
  categories: CategorySteeringCategory[];
  semanticNodes: SemanticNodeRecord[];
  messages: MessageRecord[];
  newsroomSections?: NewsroomSectionRecord[];
  semanticRelations: SemanticRelationRecord[];
  assignments?: AssignmentRecord[];
  referenceAttachments?: ReferenceAttachmentRecord[];
};

export function semanticStateKey(kind: string, lineageId: string, state = "current"): string {
  return `${kind}#${lineageId}#${state}`;
}

export function semanticVersionKey(kind: string, versionId: string): string {
  return `${kind}#${versionId}`;
}

export function semanticObjectSubjectStateKey(objectKind: string, objectLineageId: string, subjectKind: string, state = "current"): string {
  return `${objectKind}#${objectLineageId}#${state}#${subjectKind}`;
}

export function semanticPredicateObjectStateKey(predicate: string, objectKind: string, objectLineageId: string, state = "current"): string {
  return `${predicate}#${objectKind}#${objectLineageId}#${state}`;
}

export function relationTypeKey(relation: Pick<SemanticRelationRecord, "predicate" | "relationTypeKey">): string {
  return relation.relationTypeKey ?? relation.predicate;
}

export function relationDomain(relation: Pick<SemanticRelationRecord, "predicate" | "relationTypeKey" | "relationDomain">): string {
  if (relation.relationDomain) return relation.relationDomain;
  return SEMANTIC_PREDICATES.find((entry) => entry.id === relationTypeKey(relation))?.group ?? "generic";
}

export function predicateLabel(predicate: string, direction: "outgoing" | "incoming" = "outgoing"): string {
  const definition = SEMANTIC_PREDICATES.find((entry) => entry.id === predicate);
  if (!definition) return predicate.replaceAll("_", " ");
  return direction === "incoming" ? definition.inverseLabel : definition.label;
}

export function newsDeskHrefForSemanticObject(kind: string, lineageId: string): string {
  return toPublicNewsroomPath(internalNewsDeskHrefForSemanticObject(kind, lineageId));
}

function internalNewsDeskHrefForSemanticObject(kind: string, lineageId: string): string {
  const encoded = encodeURIComponent(lineageId);
  if (kind === "reference") return `/newsroom/references/${encoded}`;
  if (kind === "category") return `/newsroom/topics?category=${encoded}`;
  if (kind === "semanticNode") return `/newsroom/concepts?node=${encoded}`;
  if (kind === "assignment") return `/newsroom/assignments?assignment=${encoded}`;
  if (kind === "item") return `/newsroom?item=${encoded}`;
  if (kind === "message") return `/newsroom/messages?message=${encoded}`;
  if (kind === "newsroomSection") return `/newsroom/sections/${encoded}`;
  return `/newsroom?object=${encodeURIComponent(kind)}:${encoded}`;
}

export function createSemanticGraphSnapshot(input: SemanticGraphSnapshotInput) {
  return new SemanticGraphSnapshot(input);
}

export class SemanticGraphSnapshot {
  private referencesById = new Map<string, ReferenceRecord>();
  private referencesByLineage = new Map<string, ReferenceRecord>();
  private categoriesById = new Map<string, CategorySteeringCategory>();
  private categoriesByLineage = new Map<string, CategorySteeringCategory>();
  private semanticNodesById = new Map<string, SemanticNodeRecord>();
  private semanticNodesByLineage = new Map<string, SemanticNodeRecord>();
  private messagesById = new Map<string, MessageRecord>();
  private assignmentsById = new Map<string, AssignmentRecord>();
  private newsroomSectionsById = new Map<string, NewsroomSectionRecord>();
  private relationsBySubjectState = new Map<string, SemanticRelationRecord[]>();
  private relationsByObjectState = new Map<string, SemanticRelationRecord[]>();

  readonly attachmentsByReferenceLineage = new Map<string, ReferenceAttachmentRecord[]>();

  constructor(private input: SemanticGraphSnapshotInput) {
    for (const reference of input.references) {
      indexVersionedRecord(reference, this.referencesById, this.referencesByLineage);
    }
    for (const category of input.categories) {
      indexVersionedRecord(category, this.categoriesById, this.categoriesByLineage);
    }
    for (const node of input.semanticNodes) {
      indexVersionedRecord(node, this.semanticNodesById, this.semanticNodesByLineage);
    }
    for (const message of input.messages) {
      this.messagesById.set(message.id, message);
    }
    for (const assignment of input.assignments ?? []) {
      this.assignmentsById.set(assignment.id, assignment);
    }
    for (const section of input.newsroomSections ?? []) {
      this.newsroomSectionsById.set(section.id, section);
    }
    for (const relation of input.semanticRelations.filter((entry) => entry.relationState === "current")) {
      pushMap(this.relationsBySubjectState, relation.subjectStateKey, relation);
      pushMap(this.relationsByObjectState, relation.objectStateKey, relation);
    }
    for (const attachment of input.referenceAttachments ?? []) {
      pushMap(this.attachmentsByReferenceLineage, attachment.referenceLineageId, attachment);
    }
  }

  resolve(kind: string, idOrLineageId: string): SemanticObjectSummary | null {
    if (!idOrLineageId) return null;
    if (kind === "reference") return summarizeReference(this.referencesByLineage.get(idOrLineageId) ?? this.referencesById.get(idOrLineageId) ?? null);
    if (kind === "category") return summarizeCategory(this.categoriesByLineage.get(idOrLineageId) ?? this.categoriesById.get(idOrLineageId) ?? null);
    if (kind === "semanticNode") return summarizeSemanticNode(this.semanticNodesByLineage.get(idOrLineageId) ?? this.semanticNodesById.get(idOrLineageId) ?? null);
    if (kind === "message") return summarizeMessage(this.messagesById.get(idOrLineageId) ?? null);
    if (kind === "assignment") return summarizeAssignment(this.assignmentsById.get(idOrLineageId) ?? null);
    if (kind === "newsroomSection") return summarizeNewsroomSection(this.newsroomSectionsById.get(idOrLineageId) ?? null);
    return null;
  }

  resolveRelationObject(relation: SemanticRelationRecord, direction: "outgoing" | "incoming"): SemanticObjectSummary | null {
    return direction === "outgoing"
      ? this.resolve(relation.objectKind, relation.objectLineageId) ?? fallbackRelationObject(relation, "object")
      : this.resolve(relation.subjectKind, relation.subjectLineageId) ?? fallbackRelationObject(relation, "subject");
  }

  outgoing(kind: string, lineageId: string): SemanticRelationRecord[] {
    return this.relationsBySubjectState.get(semanticStateKey(kind, lineageId)) ?? [];
  }

  incoming(kind: string, lineageId: string): SemanticRelationRecord[] {
    return this.relationsByObjectState.get(semanticStateKey(kind, lineageId)) ?? [];
  }

  neighbors(kind: string, lineageId: string): SemanticNeighborGroup[] {
    const groups: SemanticNeighborGroup[] = [];
    groups.push(...groupRelations(this.outgoing(kind, lineageId), "outgoing", (relation) => this.resolveRelationObject(relation, "outgoing")));
    groups.push(...groupRelations(this.incoming(kind, lineageId), "incoming", (relation) => this.resolveRelationObject(relation, "incoming")));
    return groups;
  }

  referencesForCategory(categoryLineageId: string): SemanticObjectSummary[] {
    return this.subjectsForObject("category", categoryLineageId, "reference", "classified_as")
      .filter(isEvidenceEligibleReferenceSummary);
  }

  referencesForSemanticNode(nodeLineageId: string, predicate?: string): SemanticObjectSummary[] {
    return this.subjectsForObject("semanticNode", nodeLineageId, "reference", predicate)
      .filter(isEvidenceEligibleReferenceSummary);
  }

  subjectsForObject(objectKind: string, objectLineageId: string, subjectKind: string, predicate?: string): SemanticObjectSummary[] {
    const relations = this.incoming(objectKind, objectLineageId)
      .filter((relation) => relation.subjectKind === subjectKind)
      .filter((relation) => !predicate || relationTypeKey(relation) === predicate || relation.predicate === predicate);
    return uniqueSemanticObjects(relations.map((relation) => this.resolve(relation.subjectKind, relation.subjectLineageId) ?? fallbackRelationObject(relation, "subject")));
  }

  messagesFor(kind: string, lineageId: string): MessageRecord[] {
    const incomingCommentMessages = this.incoming(kind, lineageId)
      .filter((relation) => relation.subjectKind === "message")
      .filter((relation) => ["comment", "ingestion_rationale"].includes(relationTypeKey(relation)) || ["comment", "ingestion_rationale"].includes(relation.predicate))
      .map((relation) => this.messagesById.get(relation.subjectId))
      .filter((message): message is MessageRecord => Boolean(message));
    const producedMessages = this.outgoing(kind, lineageId)
      .filter((relation) => relation.objectKind === "message")
      .filter((relation) => relationTypeKey(relation) === "produces" || relation.predicate === "produces")
      .map((relation) => this.messagesById.get(relation.objectId))
      .filter((message): message is MessageRecord => Boolean(message));
    return uniqueBy([...incomingCommentMessages, ...producedMessages], (message) => message.id)
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }

  summariesFor(kind: string, lineageId: string): MessageRecord[] {
    const ranked = this.incoming(kind, lineageId)
      .filter((relation) => relation.subjectKind === "message")
      .filter((relation) => isReferenceSummaryPredicate(relationTypeKey(relation)) || isReferenceSummaryPredicate(relation.predicate))
      .map((relation) => ({
        rank: summaryPredicateRank(relationTypeKey(relation)),
        message: this.messagesById.get(relation.subjectId),
      }))
      .filter((entry): entry is { rank: number; message: MessageRecord } => Boolean(entry.message && entry.message.messageKind === "reference_summary"));
    ranked.sort((left, right) => left.rank - right.rank || right.message.createdAt.localeCompare(left.message.createdAt));
    return ranked.map((entry) => entry.message);
  }

  insightsFor(kind: string, lineageId: string): MessageRecord[] {
    return this.incoming(kind, lineageId)
      .filter((relation) => relation.subjectKind === "message")
      .filter((relation) => relationTypeKey(relation) === "insight_about" || relation.predicate === "insight_about")
      .map((relation) => this.messagesById.get(relation.subjectId))
      .filter((message): message is MessageRecord => Boolean(message))
      .filter((message) => message.messageKind === "insight" && message.messageDomain === "knowledge")
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }

  currentReferenceQualityRating(referenceLineageId: string): number | null {
    const relation = this.outgoing("reference", referenceLineageId)
      .find((entry) => relationTypeKey(entry) === "quality_rating_is" || entry.predicate === "quality_rating_is");
    return relation ? qualityRatingFromRelation(relation) : null;
  }

  attachmentsForReference(referenceLineageId: string): ReferenceAttachmentRecord[] {
    return (this.attachmentsByReferenceLineage.get(referenceLineageId) ?? []).sort((left, right) => left.sortKey.localeCompare(right.sortKey));
  }

  walk(kind: string, lineageId: string, depth = 2): SemanticWalkResult {
    const start = this.resolve(kind, lineageId);
    if (!start) return { start: null, nodes: [], edges: [], warnings: [`Missing start object ${kind}#${lineageId}`] };
    const nodes = new Map<string, SemanticObjectSummary>([[`${start.kind}#${start.lineageId}`, start]]);
    const edges = new Map<string, SemanticRelationRecord>();
    let frontier = [start];
    for (let level = 0; level < Math.max(0, depth); level += 1) {
      const nextFrontier: SemanticObjectSummary[] = [];
      for (const node of frontier) {
        for (const relation of [...this.outgoing(node.kind, node.lineageId), ...this.incoming(node.kind, node.lineageId)]) {
          edges.set(relation.id, relation);
          const neighbor = relation.subjectLineageId === node.lineageId && relation.subjectKind === node.kind
            ? this.resolveRelationObject(relation, "outgoing")
            : this.resolveRelationObject(relation, "incoming");
          if (!neighbor) continue;
          const key = `${neighbor.kind}#${neighbor.lineageId}`;
          if (!nodes.has(key)) {
            nodes.set(key, neighbor);
            nextFrontier.push(neighbor);
          }
        }
      }
      frontier = nextFrontier;
      if (!frontier.length) break;
    }
    return { start, nodes: Array.from(nodes.values()), edges: Array.from(edges.values()), warnings: [] };
  }
}

function indexVersionedRecord<T extends { id: string; lineageId?: string | null; versionState?: string | null; versionNumber?: number | null }>(
  record: T,
  byId: Map<string, T>,
  byLineage: Map<string, T>,
) {
  byId.set(record.id, record);
  const lineageId = record.lineageId ?? record.id;
  const current = byLineage.get(lineageId);
  if (!current || record.versionState === "current" || Number(record.versionNumber ?? 0) > Number(current.versionNumber ?? 0)) {
    byLineage.set(lineageId, record);
  }
}

function groupRelations(
  relations: SemanticRelationRecord[],
  direction: "outgoing" | "incoming",
  objectFor: (relation: SemanticRelationRecord) => SemanticObjectSummary | null,
): SemanticNeighborGroup[] {
  const groups = new Map<string, SemanticRelationRecord[]>();
  for (const relation of relations) pushMap(groups, relationTypeKey(relation), relation);
  return Array.from(groups.entries()).map(([predicate, entries]) => ({
    predicate,
    label: predicateLabel(predicate, direction),
    direction,
    relations: entries.sort(compareRelations),
    objects: uniqueSemanticObjects(entries.map(objectFor)),
  }));
}

function compareRelations(left: SemanticRelationRecord, right: SemanticRelationRecord): number {
  const rankDiff = (left.rank ?? 999999) - (right.rank ?? 999999);
  if (rankDiff !== 0) return rankDiff;
  return (right.score ?? 0) - (left.score ?? 0);
}

function uniqueSemanticObjects(objects: Array<SemanticObjectSummary | null>): SemanticObjectSummary[] {
  const map = new Map<string, SemanticObjectSummary>();
  for (const object of objects) {
    if (!object) continue;
    map.set(`${object.kind}#${object.lineageId}`, object);
  }
  return Array.from(map.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function isEvidenceEligibleReferenceSummary(summary: SemanticObjectSummary): boolean {
  return summary.kind === "reference" && isEvidenceEligibleReference(summary.record as ReferenceRecord | undefined);
}

function summarizeReference(record: ReferenceRecord | null): SemanticObjectSummary | null {
  if (!record) return null;
  const lineageId = record.lineageId ?? record.id;
  return {
    kind: "reference",
    id: record.id,
    lineageId,
    versionNumber: record.versionNumber,
    label: record.title ?? record.externalItemId,
    subtitle: record.mediaType ?? record.storagePath ?? record.sourceUri,
    href: newsDeskHrefForSemanticObject("reference", lineageId),
    record,
  };
}

function summarizeCategory(record: CategorySteeringCategory | null): SemanticObjectSummary | null {
  if (!record) return null;
  const lineageId = record.lineageId ?? record.id;
  return {
    kind: "category",
    id: record.id,
    lineageId,
    versionNumber: record.versionNumber,
    label: record.displayName,
    subtitle: record.subtitle ?? record.categoryKey,
    href: newsDeskHrefForSemanticObject("category", lineageId),
    record,
  };
}

function summarizeSemanticNode(record: SemanticNodeRecord | null): SemanticObjectSummary | null {
  if (!record) return null;
  const lineageId = record.lineageId ?? record.id;
  return {
    kind: "semanticNode",
    id: record.id,
    lineageId,
    versionNumber: record.versionNumber,
    label: record.displayName ?? record.nodeKey,
    subtitle: record.nodeKind,
    href: newsDeskHrefForSemanticObject("semanticNode", lineageId),
    record,
  };
}

function summarizeMessage(record: MessageRecord | null): SemanticObjectSummary | null {
  if (!record) return null;
  const lineageId = record.id;
  return {
    kind: "message",
    id: record.id,
    lineageId,
    versionNumber: 1,
    label: record.summary ?? record.messageKind,
    subtitle: record.source ?? record.messageDomain,
    href: newsDeskHrefForSemanticObject("message", lineageId),
    record,
  };
}

function summarizeAssignment(record: AssignmentRecord | null): SemanticObjectSummary | null {
  if (!record) return null;
  return {
    kind: "assignment",
    id: record.id,
    lineageId: record.id,
    label: record.title,
    subtitle: `${record.assignmentTypeKey} / ${record.status}`,
    href: newsDeskHrefForSemanticObject("assignment", record.id),
    record,
  };
}

function summarizeNewsroomSection(record: NewsroomSectionRecord | null): SemanticObjectSummary | null {
  if (!record) return null;
  return {
    kind: "newsroomSection",
    id: record.id,
    lineageId: record.id,
    label: record.title,
    subtitle: record.type,
    href: newsDeskHrefForSemanticObject("newsroomSection", record.id),
    record,
  };
}

function fallbackRelationObject(relation: SemanticRelationRecord, side: "subject" | "object"): SemanticObjectSummary {
  const kind = (side === "subject" ? relation.subjectKind : relation.objectKind) as SemanticObjectKind;
  const id = side === "subject" ? relation.subjectId : relation.objectId;
  const lineageId = side === "subject" ? relation.subjectLineageId : relation.objectLineageId;
  const versionNumber = side === "subject" ? relation.subjectVersionNumber : relation.objectVersionNumber;
  return {
    kind,
    id,
    lineageId,
    versionNumber,
    label: `${kind} ${lineageId}`,
    href: newsDeskHrefForSemanticObject(kind, lineageId),
  };
}

function qualityRatingFromRelation(relation: Pick<SemanticRelationRecord, "score" | "objectLineageId" | "objectId">): number | null {
  const score = typeof relation.score === "number" ? relation.score : Number(relation.score);
  if (Number.isFinite(score) && Number.isInteger(score) && score >= 1 && score <= 5) return score;
  return qualityRatingFromNodeKey(relation.objectLineageId) ?? qualityRatingFromNodeKey(relation.objectId);
}

function qualityRatingFromNodeKey(value: string | null | undefined): number | null {
  const match = /(?:quality[-_.]?rating[-_.]?)?([1-5])[-_.]?star/i.exec(value ?? "");
  return match ? Number(match[1]) : null;
}

function pushMap<K, V>(map: Map<K, V[]>, key: K, value: V) {
  const values = map.get(key) ?? [];
  values.push(value);
  map.set(key, values);
}

export const REFERENCE_SUMMARY_PREDICATES = [
  "reference_summary_100_tokens",
  "reference_summary_200_tokens",
  "reference_summary_500_tokens",
] as const;

function isReferenceSummaryPredicate(predicate: string): boolean {
  return REFERENCE_SUMMARY_PREDICATES.includes(predicate as typeof REFERENCE_SUMMARY_PREDICATES[number])
    || predicate.startsWith("reference_summary_");
}

function summaryPredicateRank(predicate: string): number {
  if (predicate === "reference_summary_100_tokens") return 0;
  if (predicate === "reference_summary_200_tokens") return 1;
  if (predicate === "reference_summary_500_tokens") return 2;
  return 3;
}

function uniqueBy<T>(values: T[], key: (value: T) => string): T[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const resolved = key(value);
    if (seen.has(resolved)) return false;
    seen.add(resolved);
    return true;
  });
}
