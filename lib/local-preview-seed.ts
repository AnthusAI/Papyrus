import type { AssignmentRecord, MessageRecord, ReferenceRecord, SemanticRelationRecord } from "./category-repository";
import { SHADOW_AGREEMENT_SCHEMA, type ShadowAgreement } from "./cyclotron-suggestions";
import type { EditableArticle } from "./newsroom-articles";
import type { MediaAssetRecord } from "./newsroom-media";
import { EMPTY_STORY_REPORTING_TRAIL, type StoryReportingTrail, type TrailVersion } from "./story-reporting-trail";
import { contentItemStageKeys, type ContentItemVersionRecord } from "./content-item-lifecycle";
import { getContentItemStageDefinitions } from "./site-brand";

const SEED_TIMESTAMP_BASE = Date.parse("2026-10-01T12:00:00.000Z");
const ONE_HOUR_IN_MILLISECONDS = 60 * 60 * 1000;

const SEED_CONTENT_ITEM_HEADLINES_BY_POSITION: readonly (readonly string[])[] = [
  ["Three sources confirm the zoning reversal", "Reporting packet: school board redistricting"],
  ["Draft in progress: the last ferry crossing", "Draft in progress: neighborhood bakery profile"],
  ["Illustration brief: flooded streets, aerial view", "Illustration brief: the market at dawn"],
  ["Layout pass: front page lead and rail", "Layout pass: the Saturday supplement"],
  ["Published: harbor safety review", "Published: the lighthouse keepers' archive"],
  ["Held for the winter issue: the lighthouse keepers' archive", "Evergreen: how the harbor dredging works"],
  ["Spiked: the unconfirmed council rumor", "Spiked: the recycled press release"],
];

function isoTimestampHoursBeforeBase(hours: number): string {
  return new Date(SEED_TIMESTAMP_BASE - hours * ONE_HOUR_IN_MILLISECONDS).toISOString();
}

function slugFromHeadline(headline: string): string {
  return headline.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export function createLocalPreviewContentItemVersions(): ContentItemVersionRecord[] {
  const stageKeys = contentItemStageKeys(getContentItemStageDefinitions());
  return stageKeys.flatMap((stageKey, stageIndex) => {
    const headlines = SEED_CONTENT_ITEM_HEADLINES_BY_POSITION[stageIndex % SEED_CONTENT_ITEM_HEADLINES_BY_POSITION.length];
    return headlines.map((headline, headlineIndex) => {
      const slug = slugFromHeadline(headline);
      return {
        id: `preview-item-version-${stageKey}-${headlineIndex}`,
        lineageId: `preview-item-lineage-${stageKey}-${headlineIndex}`,
        versionNumber: 1,
        stage: stageKey,
        type: "article",
        status: stageKey === "published" ? "published" : "draft",
        title: headline,
        headline,
        slug,
        section: headlineIndex === 0 ? "news" : "features",
        updatedAt: isoTimestampHoursBeforeBase(stageIndex * 3 + headlineIndex),
      };
    });
  });
}

export function createLocalPreviewReferences(): ReferenceRecord[] {
  const curationStatuses = ["pending", "accepted", "accepted", "rejected", "pending"];
  return curationStatuses.map((curationStatus, index) => ({
    id: `preview-reference-${index}`,
    lineageId: `preview-reference-lineage-${index}`,
    versionNumber: 1,
    versionState: "current",
    corpusId: "preview-corpus",
    externalItemId: `preview-source-${index}`,
    title: `Source document ${index + 1}: municipal filing excerpt`,
    curationStatus,
    curationStatusKey: curationStatus,
    curationStatusReason: curationStatus === "rejected" ? "Duplicate of an earlier filing." : null,
    importedAt: isoTimestampHoursBeforeBase(index * 5),
    updatedAt: isoTimestampHoursBeforeBase(index * 5),
  }));
}

export function createLocalPreviewAssignments(): AssignmentRecord[] {
  const contentItemVersions = createLocalPreviewContentItemVersions();
  const assignmentTypeKeys = ["research", "reporting", "copywriting"];
  const statuses = ["queued", "claimed", "completed"];
  const assignmentsOnContentItems = contentItemVersions.slice(0, 9).map((version, index) => ({
    id: `preview-assignment-${index}`,
    assignmentTypeKey: assignmentTypeKeys[index % assignmentTypeKeys.length],
    queueKey: assignmentTypeKeys[index % assignmentTypeKeys.length],
    queueStatusKey: `${assignmentTypeKeys[index % assignmentTypeKeys.length]}#${statuses[index % statuses.length]}`,
    status: statuses[index % statuses.length],
    priority: 2,
    title: `${assignmentTypeKeys[index % assignmentTypeKeys.length]} for: ${version.headline}`,
    itemLineageId: version.lineageId,
    createdAt: isoTimestampHoursBeforeBase(index * 2),
    updatedAt: isoTimestampHoursBeforeBase(index * 2),
  }));
  const assignmentsWithoutContentItem = ["Pitch: community radio partnership", "Backfill the archive index"].map((title, index) => ({
    id: `preview-assignment-standalone-${index}`,
    assignmentTypeKey: "research",
    queueKey: "research",
    queueStatusKey: "research#queued",
    status: "queued",
    priority: 2,
    title,
    createdAt: isoTimestampHoursBeforeBase(index),
    updatedAt: isoTimestampHoursBeforeBase(index),
  }));
  return [...assignmentsOnContentItems, ...assignmentsWithoutContentItem];
}

export function createLocalPreviewRealPublishedVersions(): ContentItemVersionRecord[] {
  return [];
}

export function createLocalPreviewEditableArticle(id: string): EditableArticle | null {
  const version = createLocalPreviewContentItemVersions().find(candidate => candidate.id === id);
  if (!version) return null;
  const headline = version.headline || version.title || version.slug;
  return {
    id: version.id,
    lineageId: version.lineageId,
    type: version.type,
    section: version.section ?? null,
    slug: version.slug,
    frontMatterYaml: `title: ${headline}\nsection: ${version.section ?? ""}`,
    bodyMarkus: `# ${headline}\n\nThe local preview shows this story's record. Its full body text is loaded from the live backend.`,
    contentHash: null,
    status: version.status === "published" ? "published" : "draft",
    versionNumber: version.versionNumber,
    aliases: [],
    everPublished: version.status === "published",
  };
}

export function recordLocalPreviewDesk(articleId: string, deskId: string | null): void {
  const version = createLocalPreviewContentItemVersions().find(candidate => candidate.id === articleId);
  if (version) version.section = deskId;
}

const previewSavedVersions = new Map<string, TrailVersion[]>();
const previewLineageByVersionId = new Map<string, string>();

export function recordLocalPreviewVersion(lineageId: string, version: TrailVersion): void {
  previewSavedVersions.set(lineageId, [version, ...(previewSavedVersions.get(lineageId) ?? [])]);
  previewLineageByVersionId.set(version.id, lineageId);
}

export function lineageForPreviewVersion(versionId: string): string | null {
  return previewLineageByVersionId.get(versionId) ?? null;
}

export function createLocalPreviewReportingTrail(lineageId: string): StoryReportingTrail {
  const saved = previewSavedVersions.get(lineageId) ?? [];
  return { ...EMPTY_STORY_REPORTING_TRAIL, versions: saved };
}

export function createLocalPreviewMediaAssets(_itemId: string): MediaAssetRecord[] {
  return [];
}

type PreviewSuggestionPlan = {
  label: "include" | "exclude";
  confidence: number;
  curation: "none" | "human" | "service";
  provenance: boolean;
};

const PREVIEW_SUGGESTION_PLANS: readonly PreviewSuggestionPlan[] = [
  { label: "include", confidence: 0.91, curation: "none", provenance: true },
  { label: "include", confidence: 0.86, curation: "human", provenance: true },
  { label: "exclude", confidence: 0.72, curation: "service", provenance: true },
  { label: "exclude", confidence: 0.88, curation: "human", provenance: true },
  { label: "exclude", confidence: 0.64, curation: "none", provenance: false },
];

const PREVIEW_CYCLOTRON_ID = "papyrus-relevance";

/**
 * Fixture data for reviewing the cyclotron suggestion UI without a backend:
 * suggestions with provenance on the first references, a mix of human and
 * non-human curation messages, and a live-agreement payload.
 */
export function createLocalPreviewCyclotronFixtures(references: ReferenceRecord[]): {
  relations: SemanticRelationRecord[];
  messages: MessageRecord[];
  shadowAgreement: ShadowAgreement;
} {
  const relations: SemanticRelationRecord[] = [];
  const messages: MessageRecord[] = [];
  references.slice(0, PREVIEW_SUGGESTION_PLANS.length).forEach((reference, index) => {
    const plan = PREVIEW_SUGGESTION_PLANS[index];
    const lineageId = reference.lineageId ?? reference.id;
    const decidedAt = isoTimestampHoursBeforeBase(40 - index);
    relations.push({
      id: `preview-relevance-relation-${index}`,
      relationState: "current",
      predicate: "relevance_decision_is",
      subjectKind: "reference",
      subjectId: reference.id,
      subjectLineageId: lineageId,
      objectKind: "semanticNode",
      objectId: `semantic-node-relevance-${plan.label}-v1`,
      objectLineageId: `semantic-node-relevance-${plan.label}`,
      subjectStateKey: `reference#${lineageId}#current`,
      objectStateKey: `semanticNode#semantic-node-relevance-${plan.label}#current`,
      objectSubjectStateKey: `semanticNode#semantic-node-relevance-${plan.label}#current#reference`,
      predicateObjectStateKey: `relevance_decision_is#semanticNode#semantic-node-relevance-${plan.label}#current`,
      subjectVersionKey: `reference#${reference.id}`,
      objectVersionKey: `semanticNode#semantic-node-relevance-${plan.label}-v1`,
      confidence: plan.confidence,
      modelVersion: "4",
      reviewRecommended: false,
      metadata: JSON.stringify({
        decisionId: `preview-decision-${index}`,
        label: plan.label,
        probabilities: { include: plan.label === "include" ? plan.confidence : 1 - plan.confidence, exclude: plan.label === "exclude" ? plan.confidence : 1 - plan.confidence },
        version: 4,
        decidedAt,
        labels: ["include", "exclude"],
        positiveLabel: "include",
        question: "Should this source be used as evidence for the publication?",
        cyclotronId: PREVIEW_CYCLOTRON_ID,
        ...(plan.provenance ? {
          provenance: {
            labelSet: ["include", "exclude"],
            doctrineFingerprint: "3f9c2a71d80b46e5",
            teachingFingerprint: "b71e04c9aa5d2f13",
            teachingLabels: 37,
            primingExamples: 6,
          },
        } : {}),
      }),
    } as SemanticRelationRecord);
    if (plan.curation !== "none") {
      const createdAt = isoTimestampHoursBeforeBase(30 - index);
      messages.push({
        id: `preview-curation-message-${index}`,
        messageKind: "reference_curation",
        messageDomain: "commentary",
        status: "active",
        summary: `${reference.title ?? lineageId}: curated`,
        source: "newsroom",
        createdAt,
        updatedAt: createdAt,
        metadata: JSON.stringify({
          action: reference.curationStatus === "rejected" ? "reject" : "accept",
          curationStatus: reference.curationStatus,
          referenceLineageId: lineageId,
          actorKind: plan.curation === "human" ? "human" : "service",
        }),
      });
    }
  });
  return {
    relations,
    messages,
    shadowAgreement: {
      schema: SHADOW_AGREEMENT_SCHEMA,
      comparisons: 23,
      agreement: 0.87,
      precision: 0.9,
      recall: 0.82,
      confusion: { truePositive: 9, falsePositive: 1, falseNegative: 2, trueNegative: 11 },
      computedAt: isoTimestampHoursBeforeBase(3),
      positiveLabel: "include",
      enabled: true,
      stoppedBecause: null,
    },
  };
}
