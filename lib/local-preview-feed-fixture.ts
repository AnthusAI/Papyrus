import fs from "node:fs";
import path from "node:path";
import { normalizeReviewRow } from "./review-requests";
import type { CategorySteeringDashboard, ReferenceAttachmentRecord, ReferenceRecord, SemanticRelationRecord } from "./category-repository";

/**
 * Local preview only (server side): when PAPYRUS_FEED_FIXTURE names a JSON file written by
 * scripts/export-reference-feed-fixture.py, the demo newsroom shows those References, their previews and the Cyclotron's
 * decisions instead of the invented sample. Without the variable, or without the file, nothing changes.
 */
export type ReferenceFeedFixture = {
  references: ReferenceRecord[];
  referenceAttachments: ReferenceAttachmentRecord[];
  semanticRelations: SemanticRelationRecord[];
};

export function loadReferenceFeedFixture(env: NodeJS.ProcessEnv = process.env): ReferenceFeedFixture | null {
  const configured = env.PAPYRUS_FEED_FIXTURE?.trim();
  if (!configured || env.NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW !== "1") return null;
  try {
    const parsed = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), configured), "utf8"));
    if (parsed?.schema !== "papyrus-reference-feed-fixture/1" || !Array.isArray(parsed.references)) return null;
    return {
      references: parsed.references,
      referenceAttachments: Array.isArray(parsed.referenceAttachments) ? parsed.referenceAttachments : [],
      semanticRelations: Array.isArray(parsed.semanticRelations) ? parsed.semanticRelations : [],
    };
  } catch {
    return null;
  }
}

export type NotificationCenterFixture = NonNullable<CategorySteeringDashboard["notificationFixture"]>;

/**
 * Local preview only: when PAPYRUS_NOTIFICATION_FIXTURE names a JSON file written by scripts/export-notification-center-fixture.py,
 * the demo Notification Center shows those review requests instead of the invented sample.
 */
export function loadNotificationCenterFixture(env: NodeJS.ProcessEnv = process.env): NotificationCenterFixture | null {
  const configured = env.PAPYRUS_NOTIFICATION_FIXTURE?.trim();
  if (!configured || env.NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW !== "1") return null;
  try {
    const parsed = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), configured), "utf8"));
    if (parsed?.schema !== "papyrus-notification-center-fixture/1" || !Array.isArray(parsed.requests)) return null;
    return { requests: parsed.requests.map(normalizeReviewRow) };
  } catch {
    return null;
  }
}

export function withReferenceFeedFixture(dashboard: CategorySteeringDashboard): CategorySteeringDashboard {
  const fixture = loadReferenceFeedFixture();
  if (!fixture) return dashboard;
  return {
    ...dashboard,
    notificationFixture: loadNotificationCenterFixture(),
    references: fixture.references,
    referenceAttachments: fixture.referenceAttachments,
    semanticRelations: fixture.semanticRelations,
    messages: [],
    realDataPreview: true,
  };
}
