import type {
  AssignmentEventRecord,
  AssignmentRecord,
  EditionSlotRecord,
  MessageRecord,
  NewsroomSectionRecord,
  SemanticRelationRecord,
} from "./category-repository";

export type ReportingStoryBudgetDecision = "select" | "merge" | "brief" | "hold" | "kill";
export type ReportingStoryBudgetPhase = "plan" | "research" | "reporting" | "review" | "copywriting" | "draft";

export type ReportingStoryBudgetCandidate = {
  assignment: AssignmentRecord;
  assignmentId: string;
  title: string;
  editionId: string;
  editionLabel: string;
  sectionKey: string;
  sectionTitle: string;
  topicKey: string | null;
  coverageThemeRunId: string | null;
  phase: ReportingStoryBudgetPhase;
  coverageConceptId: string | null;
  coverageConceptTitle: string | null;
  slotId: string | null;
  slotRank: number | null;
  candidateRank: number | null;
  slotCount: number | null;
  hasReportingPacket: boolean;
  reportingPacketId: string | null;
  researchPacketCount: number;
  summary: string | null;
  editorRecommendation: string | null;
  recommendedAngle: string | null;
  riskFlags: string[];
  coverageGaps: string[];
  openQuestions: string[];
  acceptedReferenceCount: number;
  proposedReferenceCount: number;
  decision: ReportingStoryBudgetDecision | null;
  decisionEventId: string | null;
  degraded: boolean;
  fallbackReason: string | null;
  agentExitStatus: number | null;
  copywritingAssignmentId: string | null;
  copywritingStatus: string | null;
  producedDraftItemId: string | null;
  draftItemId: string | null;
  targetItemId: string | null;
};

export type ReportingStoryBudgetSlot = {
  slotId: string;
  slotRank: number | null;
  targetType: string;
  targetLengthBand: string | null;
  minImageAssets: number | null;
  status: string;
  selectedAssignmentId: string | null;
  candidateCount: number;
  filled: boolean;
  candidates: ReportingStoryBudgetCandidate[];
};

export type ReportingStoryBudgetSection = {
  key: string;
  title: string;
  editionId: string;
  editionLabel: string;
  slotCount: number;
  dispatchedCount: number;
  selectedCount: number;
  briefedCount: number;
  mergedCount: number;
  heldCount: number;
  killedCount: number;
  undecidedCount: number;
  filledCount: number;
  delta: number;
  state: "needs" | "full" | "over";
  filledSlotCount: number;
  unresolvedSlotCount: number;
  slots: ReportingStoryBudgetSlot[];
  candidates: ReportingStoryBudgetCandidate[];
  phase: ReportingStoryBudgetPhase;
  researchPacketCount: number;
  reportingPacketCount: number;
  copywritingAssignmentCount: number;
  draftItemCount: number;
  degradedCount: number;
};

export type ReportingStoryBudget = {
  sections: ReportingStoryBudgetSection[];
  totals: Omit<ReportingStoryBudgetSection, "key" | "title" | "editionId" | "editionLabel" | "candidates" | "slots">;
};

export type ReportingStoryBudgetInput = {
  assignments: AssignmentRecord[];
  messages: MessageRecord[];
  assignmentEvents: AssignmentEventRecord[];
  semanticRelations: SemanticRelationRecord[];
  editionSlots?: EditionSlotRecord[];
  newsroomSections?: NewsroomSectionRecord[];
  messagePayloads?: Record<string, unknown>;
};

const REPORTING_ASSIGNMENT_TYPE = "reporting.candidate";
const REPORTING_PACKET_KIND = "reporting_context_packet";
const RESEARCH_PACKET_KIND = "research_packet";

export function buildReportingStoryBudget(input: ReportingStoryBudgetInput): ReportingStoryBudget {
  const sectionsByKey = new Map((input.newsroomSections ?? []).map((section) => [section.id, section]));
  const editionSlots = input.editionSlots ?? [];
  const editionSlotById = new Map(editionSlots.map((slot) => [slot.id, slot]));
  const linkedMessageIdsByAssignment = buildLinkedMessageIdsByAssignment(input.semanticRelations ?? []);
  const relationsByAssignment = groupRelationsByAssignment(input.semanticRelations ?? []);
  const researchPacketIdsByReportingAssignment = buildResearchPacketIdsByReportingAssignment(input.assignments ?? [], input.messages ?? [], input.semanticRelations ?? []);
  const copywritingByReportingAssignment = buildCopywritingByReportingAssignment(input.assignments ?? [], input.semanticRelations ?? []);
  const producedDraftItemByCopywritingAssignment = buildProducedItemByAssignment(input.semanticRelations ?? []);
  const messagesById = new Map((input.messages ?? []).map((message) => [message.id, message]));
  const candidates = (input.assignments ?? [])
    .filter((assignment) => assignment.assignmentTypeKey === REPORTING_ASSIGNMENT_TYPE)
    .map((assignment) => {
      const linkedMessages = (linkedMessageIdsByAssignment.get(assignment.id) ?? [])
        .map((id) => messagesById.get(id))
        .filter((message): message is MessageRecord => Boolean(message));
      const fallbackMessages = linkedMessages.length
        ? linkedMessages
        : (input.messages ?? []).filter((message) => metadataAssignmentId(message.metadata) === assignment.id);
      const reportingMessages = fallbackMessages
        .filter((message) => message.messageKind === REPORTING_PACKET_KIND)
        .sort(compareCreatedAtDesc);
      const reportingMessage = reportingMessages[0] ?? null;
      const packet = reportingMessage ? reportingPacketMetadata(reportingMessage, input.messagePayloads?.[reportingMessage.id]) : {};
      const assignmentMetadata = parseObject(assignment.metadata);
      const coverageThemeRunId = normalizeString(packet.coverageThemeRunId)
        ?? normalizeString(packet.storyCycleRunId)
        ?? normalizeString(assignmentMetadata.coverageThemeRunId)
        ?? normalizeString(assignmentMetadata.storyCycleRunId);
      const slotTarget = parseObject(packet.slotTarget ?? assignmentMetadata.slotTarget);
      const relations = relationsByAssignment.get(assignment.id) ?? [];
      const slotRelation = relationByType(relations, "targets_slot", "editionSlot");
      const slotId = normalizeString(slotTarget.slotId)
        ?? normalizeString(slotRelation?.objectId)
        ?? normalizeString(slotRelation?.objectLineageId);
      const slot = slotId ? editionSlotById.get(slotId) : undefined;
      const topicRelation = relationByType(relations, "targets_topic", "category");
      const topicMetadata = parseObject(topicRelation?.metadata);
      const conceptRelation = relationByType(relations, "requests_work_on", "semanticNode")
        ?? relationByType(relations, "uses_signal", "semanticNode");
      const conceptMetadata = parseObject(conceptRelation?.metadata);
      const sectionKey = normalizeString(packet.sectionKey)
        ?? normalizeString(assignment.sectionKey)
        ?? normalizeString(assignment.sectionId)
        ?? normalizeString(assignmentMetadata.sectionKey)
        ?? normalizeString(assignmentMetadata.sectionId)
        ?? relationObjectId(relations, "targets_section")
        ?? "unsectioned";
      const section = sectionsByKey.get(sectionKey);
      const editionId = normalizeString(packet.editionId)
        ?? normalizeString(assignmentMetadata.editionId)
        ?? relationObjectId(relations, "planned_for_edition")
        ?? normalizeString(assignmentMetadata.editionSlug)
        ?? "unplanned";
      const decision = latestReportingDecision(input.assignmentEvents ?? [], assignment.id);
      const copywritingAssignment = decision?.copywritingAssignmentId
        ? (input.assignments ?? []).find((entry) => entry.id === decision.copywritingAssignmentId) ?? null
        : copywritingByReportingAssignment.get(assignment.id) ?? null;
      const copywritingAssignmentId = copywritingAssignment?.id ?? decision?.copywritingAssignmentId ?? null;
      const producedDraftItemId = copywritingAssignmentId
        ? producedDraftItemByCopywritingAssignment.get(copywritingAssignmentId) ?? null
        : null;
      const researchPacketCount = Math.max(
        fallbackMessages.filter((message) => message.messageKind === RESEARCH_PACKET_KIND).length,
        researchPacketIdsByReportingAssignment.get(assignment.id)?.size ?? 0,
      );
      const phase = reportingBudgetPhase({
        hasReportingPacket: Boolean(reportingMessage),
        researchPacketCount,
        decision: decision?.decision ?? null,
        copywritingAssignmentId,
        producedDraftItemId,
      });
      return {
        assignment,
        assignmentId: assignment.id,
        title: assignment.title,
        editionId,
        editionLabel: normalizeString(assignmentMetadata.editionSlug) ?? editionId,
        sectionKey,
        sectionTitle: section?.title ?? normalizeTitle(sectionKey),
        coverageThemeRunId,
        phase,
        topicKey: normalizeString(packet.topicKey)
          ?? normalizeString(assignmentMetadata.focusCategoryKey)
          ?? normalizeString(topicMetadata.categoryKey)
          ?? normalizeString(assignment.primaryFocusCategoryKey),
        coverageConceptId: normalizeString(packet.coverageConceptLineageId)
          ?? normalizeString(assignmentMetadata.coverageConceptLineageId)
          ?? normalizeString(conceptRelation?.objectLineageId),
        coverageConceptTitle: normalizeString(packet.coverageConceptTitle)
          ?? normalizeString(assignmentMetadata.coverageConceptTitle)
          ?? normalizeString(conceptMetadata.coverageConceptTitle)
          ?? normalizeString(conceptMetadata.nodeKey)
          ?? normalizeString(conceptRelation?.objectId),
        slotId: slotId ?? null,
        slotRank: normalizeNumber(slotTarget.slotRank ?? slot?.slotRank),
        candidateRank: normalizeNumber(packet.candidateRank ?? assignmentMetadata.candidateRank ?? slotTarget.candidateRank),
        slotCount: normalizeNumber(slotTarget.slots ?? assignmentMetadata.publicationSlots ?? section?.defaultPageBudget),
        hasReportingPacket: Boolean(reportingMessage),
        reportingPacketId: reportingMessage?.id ?? null,
        researchPacketCount,
        summary: normalizeString(packet.summary) ?? reportingMessage?.summary ?? assignment.summary ?? null,
        editorRecommendation: normalizeString(packet.editorRecommendation),
        recommendedAngle: normalizeString(packet.recommendedAngle),
        riskFlags: stringList(packet.riskFlags),
        coverageGaps: stringList(packet.coverageGaps),
        openQuestions: stringList(packet.openQuestions),
        acceptedReferenceCount: stringList(packet.acceptedReferenceIds).length,
        proposedReferenceCount: arrayLength(packet.proposedReferences),
        decision: decision?.decision ?? null,
        decisionEventId: decision?.eventId ?? null,
        degraded: Boolean(packet.degraded ?? packet.fallback),
        fallbackReason: normalizeString(packet.fallbackReason) ?? normalizeString(parseObject(packet.fallback).reason),
        agentExitStatus: normalizeNumberAllowZero(packet.agentExitStatus ?? packet.exitStatus),
        copywritingAssignmentId,
        copywritingStatus: copywritingAssignment?.status ?? null,
        producedDraftItemId,
        draftItemId: producedDraftItemId ?? decision?.draftItemId ?? null,
        targetItemId: decision?.targetItemId ?? null,
      };
    })
    .sort(compareCandidates);

  const grouped = new Map<string, ReportingStoryBudgetCandidate[]>();
  for (const candidate of candidates) {
    const key = `${candidate.editionId}::${candidate.sectionKey}`;
    grouped.set(key, [...(grouped.get(key) ?? []), candidate]);
  }

  const sections = Array.from(grouped.values())
    .map((sectionCandidates) => {
      const first = sectionCandidates[0];
      const sectionSlots = editionSlots.filter((slot) => (
        slot.sectionKey === first.sectionKey
        && slot.editionId === first.editionId
      ));
      return buildSectionBudget(sectionCandidates, sectionSlots);
    })
    .sort((left, right) => (
      left.editionLabel.localeCompare(right.editionLabel)
      || left.title.localeCompare(right.title)
    ));
  return {
    sections,
    totals: totalBudget(sections),
  };
}

function buildLinkedMessageIdsByAssignment(relations: SemanticRelationRecord[]): Map<string, string[]> {
  const byAssignment = new Map<string, string[]>();
  for (const relation of relations) {
    if (relation.relationState === "superseded") continue;
    const relationType = relation.relationTypeKey ?? relation.predicate;
    if (relationType === "produces" && relation.subjectKind === "assignment" && relation.objectKind === "message") {
      byAssignment.set(relation.subjectId, [...(byAssignment.get(relation.subjectId) ?? []), relation.objectId]);
      continue;
    }
    if (relationType === "comment" && relation.subjectKind === "message" && relation.objectKind === "assignment") {
      byAssignment.set(relation.objectId, [...(byAssignment.get(relation.objectId) ?? []), relation.subjectId]);
    }
  }
  return byAssignment;
}

function groupRelationsByAssignment(relations: SemanticRelationRecord[]): Map<string, SemanticRelationRecord[]> {
  const byAssignment = new Map<string, SemanticRelationRecord[]>();
  for (const relation of relations) {
    if (relation.subjectKind !== "assignment") continue;
    if (relation.relationState === "superseded") continue;
    byAssignment.set(relation.subjectId, [...(byAssignment.get(relation.subjectId) ?? []), relation]);
  }
  return byAssignment;
}

function buildCopywritingByReportingAssignment(assignments: AssignmentRecord[], relations: SemanticRelationRecord[]): Map<string, AssignmentRecord> {
  const assignmentById = new Map(assignments.map((assignment) => [assignment.id, assignment]));
  const result = new Map<string, AssignmentRecord>();
  for (const assignment of assignments) {
    if (!assignment.assignmentTypeKey.startsWith("copywriting.")) continue;
    const metadata = parseObject(assignment.metadata);
    const sourceReportingAssignmentId = normalizeString(metadata.sourceReportingAssignmentId);
    if (sourceReportingAssignmentId) result.set(sourceReportingAssignmentId, assignment);
  }
  for (const relation of relations) {
    if (relation.relationState === "superseded") continue;
    if ((relation.relationTypeKey ?? relation.predicate) !== "derived_from") continue;
    if (relation.subjectKind !== "assignment" || relation.objectKind !== "assignment") continue;
    const copywriting = assignmentById.get(relation.subjectId);
    const reporting = assignmentById.get(relation.objectId);
    if (!copywriting?.assignmentTypeKey.startsWith("copywriting.")) continue;
    if (reporting?.assignmentTypeKey !== REPORTING_ASSIGNMENT_TYPE) continue;
    result.set(reporting.id, copywriting);
  }
  return result;
}

function buildResearchPacketIdsByReportingAssignment(assignments: AssignmentRecord[], messages: MessageRecord[], relations: SemanticRelationRecord[]): Map<string, Set<string>> {
  const assignmentById = new Map(assignments.map((assignment) => [assignment.id, assignment]));
  const messageById = new Map(messages.map((message) => [message.id, message]));
  const producedResearchPacketsByAssignment = new Map<string, Set<string>>();
  const reportingPacketIdsByAssignment = new Map<string, Set<string>>();
  const result = new Map<string, Set<string>>();
  for (const relation of relations) {
    if (relation.relationState === "superseded") continue;
    if ((relation.relationTypeKey ?? relation.predicate) !== "produces") continue;
    if (relation.subjectKind !== "assignment" || relation.objectKind !== "message") continue;
    const message = messageById.get(relation.objectId);
    if (message?.messageKind === RESEARCH_PACKET_KIND) {
      producedResearchPacketsByAssignment.set(relation.subjectId, addToSet(producedResearchPacketsByAssignment.get(relation.subjectId), relation.objectId));
    }
    if (message?.messageKind === REPORTING_PACKET_KIND) {
      reportingPacketIdsByAssignment.set(relation.subjectId, addToSet(reportingPacketIdsByAssignment.get(relation.subjectId), relation.objectId));
    }
  }
  for (const relation of relations) {
    if (relation.relationState === "superseded") continue;
    if ((relation.relationTypeKey ?? relation.predicate) !== "derived_from") continue;
    if (relation.subjectKind === "assignment" && relation.objectKind === "assignment") {
      const reporting = assignmentById.get(relation.subjectId);
      const research = assignmentById.get(relation.objectId);
      if (reporting?.assignmentTypeKey !== REPORTING_ASSIGNMENT_TYPE || research?.assignmentTypeKey !== "research.candidate") continue;
      for (const packetId of producedResearchPacketsByAssignment.get(research.id) ?? []) {
        result.set(reporting.id, addToSet(result.get(reporting.id), packetId));
      }
    }
    if (relation.subjectKind === "message" && relation.objectKind === "message") {
      const researchMessage = messageById.get(relation.objectId);
      if (researchMessage?.messageKind !== RESEARCH_PACKET_KIND) continue;
      for (const [reportingAssignmentId, reportingPacketIds] of reportingPacketIdsByAssignment.entries()) {
        if (reportingPacketIds.has(relation.subjectId)) {
          result.set(reportingAssignmentId, addToSet(result.get(reportingAssignmentId), relation.objectId));
        }
      }
    }
  }
  return result;
}

function addToSet<T>(set: Set<T> | undefined, value: T): Set<T> {
  const next = set ?? new Set<T>();
  next.add(value);
  return next;
}

function buildProducedItemByAssignment(relations: SemanticRelationRecord[]): Map<string, string> {
  const result = new Map<string, string>();
  for (const relation of relations) {
    if (relation.relationState === "superseded") continue;
    if ((relation.relationTypeKey ?? relation.predicate) !== "produces") continue;
    if (relation.subjectKind !== "assignment" || relation.objectKind !== "item") continue;
    result.set(relation.subjectId, relation.objectId);
  }
  return result;
}

function relationByType(relations: SemanticRelationRecord[], predicate: string, objectKind?: string): SemanticRelationRecord | null {
  return relations.find((relation) => (
    (relation.relationTypeKey ?? relation.predicate) === predicate
    && (!objectKind || relation.objectKind === objectKind)
  )) ?? null;
}

function buildSectionBudget(candidates: ReportingStoryBudgetCandidate[], sectionSlots: EditionSlotRecord[]): ReportingStoryBudgetSection {
  const first = candidates[0];
  const inferredSlotCount = Math.max(1, ...candidates.map((candidate) => candidate.slotCount ?? 0));
  const normalizedSlots = sectionSlots.length
    ? sectionSlots
    : Array.from({ length: inferredSlotCount }, (_, index) => ({
      id: `synthetic-slot-${first.editionId}-${first.sectionKey}-${index + 1}`,
      editionId: first.editionId,
      sectionKey: first.sectionKey,
      slotRank: index + 1,
      targetType: "article",
      targetLengthBand: "standard",
      minImageAssets: null,
      status: "assigned",
      selectedAssignmentId: null,
      createdAt: first.assignment.createdAt,
      updatedAt: first.assignment.updatedAt,
    } as EditionSlotRecord));
  const candidateBySlotId = new Map<string, ReportingStoryBudgetCandidate[]>();
  for (const candidate of candidates) {
    const key = candidate.slotId ?? `synthetic-slot-${first.editionId}-${first.sectionKey}-${candidate.slotRank ?? 0}`;
    candidateBySlotId.set(key, [...(candidateBySlotId.get(key) ?? []), candidate]);
  }
  const slots: ReportingStoryBudgetSlot[] = normalizedSlots
    .map((slot) => {
      const slotCandidates = [...(candidateBySlotId.get(slot.id) ?? [])].sort(compareCandidates);
      let selectedAssignmentId = normalizeString(slot.selectedAssignmentId);
      if (!selectedAssignmentId) {
        selectedAssignmentId = slotCandidates.find((candidate) => candidate.decision === "select" || candidate.decision === "brief")?.assignmentId ?? null;
      }
      const status = String(slot.status || "open").trim().toLowerCase();
      const filled = status === "filled" || status === "selected" || status === "briefed" || Boolean(selectedAssignmentId);
      return {
        slotId: slot.id,
        slotRank: slot.slotRank ?? null,
        targetType: slot.targetType ?? "article",
        targetLengthBand: normalizeString(slot.targetLengthBand) ?? null,
        minImageAssets: typeof slot.minImageAssets === "number" ? slot.minImageAssets : null,
        status: status || "open",
        selectedAssignmentId,
        candidateCount: slotCandidates.length,
        filled,
        candidates: slotCandidates,
      };
    })
    .sort((left, right) => (left.slotRank ?? 9999) - (right.slotRank ?? 9999) || left.slotId.localeCompare(right.slotId));
  const slotCount = slots.length || inferredSlotCount;
  const selectedCount = candidates.filter((candidate) => candidate.decision === "select").length;
  const briefedCount = candidates.filter((candidate) => candidate.decision === "brief").length;
  const mergedCount = candidates.filter((candidate) => candidate.decision === "merge").length;
  const heldCount = candidates.filter((candidate) => candidate.decision === "hold").length;
  const killedCount = candidates.filter((candidate) => candidate.decision === "kill").length;
  const undecidedCount = candidates.filter((candidate) => !candidate.decision).length;
  const filledCount = slots.length ? slots.filter((slot) => slot.filled).length : selectedCount + briefedCount;
  const delta = filledCount - slotCount;
  const researchPacketCount = candidates.reduce((sum, candidate) => sum + candidate.researchPacketCount, 0);
  const reportingPacketCount = candidates.filter((candidate) => candidate.hasReportingPacket).length;
  const copywritingAssignmentCount = candidates.filter((candidate) => candidate.copywritingAssignmentId).length;
  const draftItemCount = candidates.filter((candidate) => candidate.draftItemId).length;
  const degradedCount = candidates.filter((candidate) => candidate.degraded).length;
  return {
    key: first.sectionKey,
    title: first.sectionTitle,
    editionId: first.editionId,
    editionLabel: first.editionLabel,
    slotCount,
    dispatchedCount: candidates.length,
    selectedCount,
    briefedCount,
    mergedCount,
    heldCount,
    killedCount,
    undecidedCount,
    filledCount,
    delta,
    state: delta > 0 ? "over" : delta === 0 ? "full" : "needs",
    filledSlotCount: filledCount,
    unresolvedSlotCount: Math.max(slotCount - filledCount, 0),
    slots,
    candidates,
    phase: highestReportingBudgetPhase(candidates.map((candidate) => candidate.phase)),
    researchPacketCount,
    reportingPacketCount,
    copywritingAssignmentCount,
    draftItemCount,
    degradedCount,
  };
}

function totalBudget(sections: ReportingStoryBudgetSection[]): ReportingStoryBudget["totals"] {
  const totals = sections.reduce((memo, section) => ({
    slotCount: memo.slotCount + section.slotCount,
    dispatchedCount: memo.dispatchedCount + section.dispatchedCount,
    selectedCount: memo.selectedCount + section.selectedCount,
    briefedCount: memo.briefedCount + section.briefedCount,
    mergedCount: memo.mergedCount + section.mergedCount,
    heldCount: memo.heldCount + section.heldCount,
    killedCount: memo.killedCount + section.killedCount,
    undecidedCount: memo.undecidedCount + section.undecidedCount,
    filledCount: memo.filledCount + section.filledCount,
    filledSlotCount: memo.filledSlotCount + section.filledSlotCount,
    unresolvedSlotCount: memo.unresolvedSlotCount + section.unresolvedSlotCount,
    delta: memo.delta + section.delta,
    researchPacketCount: memo.researchPacketCount + section.researchPacketCount,
    reportingPacketCount: memo.reportingPacketCount + section.reportingPacketCount,
    copywritingAssignmentCount: memo.copywritingAssignmentCount + section.copywritingAssignmentCount,
    draftItemCount: memo.draftItemCount + section.draftItemCount,
    degradedCount: memo.degradedCount + section.degradedCount,
  }), {
    slotCount: 0,
    dispatchedCount: 0,
    selectedCount: 0,
    briefedCount: 0,
    mergedCount: 0,
    heldCount: 0,
    killedCount: 0,
    undecidedCount: 0,
    filledCount: 0,
    filledSlotCount: 0,
    unresolvedSlotCount: 0,
    delta: 0,
    researchPacketCount: 0,
    reportingPacketCount: 0,
    copywritingAssignmentCount: 0,
    draftItemCount: 0,
    degradedCount: 0,
  });
  return {
    ...totals,
    state: totals.delta > 0 ? "over" : totals.delta === 0 ? "full" : "needs",
    phase: highestReportingBudgetPhase(sections.map((section) => section.phase)),
  };
}

function reportingBudgetPhase(input: {
  hasReportingPacket: boolean;
  researchPacketCount: number;
  decision: ReportingStoryBudgetDecision | null;
  copywritingAssignmentId: string | null;
  producedDraftItemId: string | null;
}): ReportingStoryBudgetPhase {
  if (input.producedDraftItemId) return "draft";
  if (input.copywritingAssignmentId) return "copywriting";
  if (input.decision) return "review";
  if (input.hasReportingPacket) return "reporting";
  if (input.researchPacketCount > 0) return "research";
  return "plan";
}

function highestReportingBudgetPhase(phases: ReportingStoryBudgetPhase[]): ReportingStoryBudgetPhase {
  const order: ReportingStoryBudgetPhase[] = ["plan", "research", "reporting", "review", "copywriting", "draft"];
  return phases.reduce((highest, phase) => (
    order.indexOf(phase) > order.indexOf(highest) ? phase : highest
  ), "plan" as ReportingStoryBudgetPhase);
}

function latestReportingDecision(events: AssignmentEventRecord[], assignmentId: string) {
  const event = events
    .filter((entry) => entry.assignmentId === assignmentId && entry.eventType.startsWith("reporting_"))
    .sort((left, right) => String(right.createdAt).localeCompare(String(left.createdAt)))[0];
  if (!event) return null;
  const metadata = parseObject(event.metadata);
  const decision = normalizeDecision(metadata.decision ?? event.eventType.replace(/^reporting_/, ""));
  if (!decision) return null;
  return {
    decision,
    eventId: event.id,
    copywritingAssignmentId: normalizeString(metadata.copywritingAssignmentId),
    draftItemId: normalizeString(metadata.draftItemId),
    targetItemId: normalizeString(metadata.targetItemId),
  };
}

function reportingPacketMetadata(message: MessageRecord, payload: unknown): Record<string, unknown> {
  const fromPayload = reportingObjectFromPayload(payload);
  if (fromPayload) return fromPayload;
  const metadata = parseObject(message.metadata);
  const reporting = parseObject(metadata.reporting);
  return Object.keys(reporting).length ? reporting : metadata;
}

function reportingObjectFromPayload(payload: unknown): Record<string, unknown> | null {
  const parsed = parseObject(payload);
  if (!Object.keys(parsed).length) return null;
  const reporting = parseObject(parsed.reporting);
  return Object.keys(reporting).length ? reporting : parsed;
}

function metadataAssignmentId(value: unknown): string | null {
  const metadata = parseObject(value);
  return normalizeString(metadata.assignmentId);
}

function relationObjectId(relations: SemanticRelationRecord[], predicate: string): string | null {
  const relation = relations.find((entry) => (entry.relationTypeKey ?? entry.predicate) === predicate);
  return relation ? normalizeString(relation.objectLineageId) ?? normalizeString(relation.objectId) : null;
}

function compareCandidates(left: ReportingStoryBudgetCandidate, right: ReportingStoryBudgetCandidate): number {
  return (
    left.editionLabel.localeCompare(right.editionLabel)
    || left.sectionTitle.localeCompare(right.sectionTitle)
    || (left.slotRank ?? 9999) - (right.slotRank ?? 9999)
    || (left.candidateRank ?? 9999) - (right.candidateRank ?? 9999)
    || left.title.localeCompare(right.title)
  );
}

function compareCreatedAtDesc(left: MessageRecord, right: MessageRecord): number {
  return String(right.createdAt).localeCompare(String(left.createdAt));
}

function parseObject(value: unknown): Record<string, unknown> {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => typeof entry === "string" ? entry.trim() : "")
    .filter(Boolean);
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function normalizeString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function normalizeNumberAllowZero(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function normalizeDecision(value: unknown): ReportingStoryBudgetDecision | null {
  const decision = String(value ?? "").trim().toLowerCase().replace(/^reporting_/, "") as ReportingStoryBudgetDecision;
  return decision === "select" || decision === "merge" || decision === "brief" || decision === "hold" || decision === "kill"
    ? decision
    : null;
}

function normalizeTitle(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || "Unsectioned";
}
