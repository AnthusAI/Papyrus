import type { AssignmentRecord, ReferenceRecord } from "./category-repository";
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
