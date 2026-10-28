"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { AssignmentRecord, NewsroomSectionRecord, ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { referenceLineageId, selectCanonicalReferenceRecords, type ReferenceCurationAction } from "../lib/newsroom-references";
import {
  buildNewsroomSectionHref,
  displayNewsroomSectionShortTitle,
  isEnabledNewsroomSection,
  newsroomDeskKind,
  sortNewsroomSections,
} from "../lib/newsroom-sections";
import { cn } from "@/lib/utils";
import { FEED_SURFACE_PROPS } from "./reference-feed";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import type { ReferenceRejectionReasonCode } from "../lib/reference-policy";
import { referencePreviewsByLineage, type ReferencePreview } from "../lib/reference-preview";
import type { NotificationFixture } from "./notification-center";
import { NotificationCenter } from "./notification-center";
import type { CorrectCaptureAction } from "./reference-capture-client";
import type { ReviewChoice } from "./reference-review-card";

type NewsroomOpsOverviewProps = {
  assignments: AssignmentRecord[];
  actorLabel?: string;
  decisions?: ReadonlyMap<string, RelevanceDecisionView>;
  demo?: boolean;
  humanCuratedReferenceLineageIds?: ReadonlySet<string>;
  newsroomSections: NewsroomSectionRecord[];
  references: ReferenceRecord[];
  referenceAttachments?: ReferenceAttachmentRecord[];
  /** True until the References have been read; a saved copy of the last view fills the page meanwhile. */
  loading?: boolean;
  savedCopy?: { references: ReferenceRecord[]; previews: Array<[string, ReferencePreview]>; decisions: Array<[string, RelevanceDecisionView]> } | null;
  predictionState?: "loading" | "ready" | "error";
  /** Words for why a rating cannot be saved right now, or null. */
  disabledReason?: string | null;
  onReview?: (reference: ReferenceRecord, action: ReferenceCurationAction, options?: { reasonCode?: ReferenceRejectionReasonCode | null; note?: string; decisionRelationId?: string; shareable?: boolean }) => Promise<void> | void;
  /** Saves a pasted or corrected capture (the `correctReferenceCapture` action). Without it the capture panel has no edit action. */
  onCorrectCapture?: CorrectCaptureAction;
  /** Local real-data preview of the Notification Center (scripts/export-notification-center-fixture.py). */
  notificationFixture?: NotificationFixture | null;
};

const NO_DECISIONS: ReadonlyMap<string, RelevanceDecisionView> = new Map();

export function NewsroomOpsOverview({
  actorLabel = "",
  assignments,
  decisions = NO_DECISIONS,
  demo = false,
  humanCuratedReferenceLineageIds,
  disabledReason = null,
  loading = false,
  newsroomSections,
  notificationFixture = null,
  onCorrectCapture,
  onReview,
  predictionState = "ready",
  referenceAttachments = [],
  references,
  savedCopy = null,
}: NewsroomOpsOverviewProps) {
  const pathname = usePathname();
  const liveReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  // Until the live read arrives, a saved copy of the last view fills the page. It is display only.
  const showingSavedCopy = loading && !liveReferences.length && Boolean(savedCopy?.references.length);
  const canonicalReferences = showingSavedCopy ? savedCopy!.references : liveReferences;
  const shownDecisions = useMemo(() => (showingSavedCopy && !decisions.size ? new Map(savedCopy!.decisions) : decisions), [decisions, savedCopy, showingSavedCopy]);
  const previews = useMemo(() => {
    const live = referencePreviewsByLineage(referenceAttachments);
    return showingSavedCopy && !live.size ? new Map(savedCopy!.previews) : live;
  }, [referenceAttachments, savedCopy, showingSavedCopy]);
  const rateReference = useCallback(async (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null, note?: string) => {
    const decision = shownDecisions.get(referenceLineageId(reference));
    await onReview?.(reference, choice, {
      reasonCode: choice === "reject" ? reasonCode : null,
      ...(note ? { note } : {}),
      ...(decision ? { decisionRelationId: decision.decisionRelationId, shareable: false } : {}),
    });
  }, [onReview, shownDecisions]);
  const attentionAssignments = useMemo(
    () => assignments
      .filter((assignment) => {
        const status = assignment.status?.trim().toLowerCase() ?? "";
        return status === "open" || status === "claimed" || status === "pending";
      })
      .slice(0, 4),
    [assignments],
  );
  const desks = useMemo(
    () => sortNewsroomSections(newsroomSections).filter(isEnabledNewsroomSection),
    [newsroomSections],
  );
  const coreDesks = useMemo(() => desks.filter(desk => newsroomDeskKind(desk) === "core"), [desks]);
  const rotatingDesks = useMemo(() => desks.filter(desk => newsroomDeskKind(desk) === "rotating"), [desks]);
  const rateDisabled = disabledReason ?? (showingSavedCopy ? "Confirming your sign-in. You can answer in a moment." : null);

  const below = (
    <div className="space-y-12 pt-6" data-newsroom-overview-below {...FEED_SURFACE_PROPS}>
        {attentionAssignments.length ? (
          <section aria-label="Open assignments" className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Open assignments</h2>
            <div className="space-y-2">
              {attentionAssignments.map((assignment) => {
                const href = getNewsroomNavHref(`/newsroom/assignments/${encodeURIComponent(assignment.id)}`, demo);
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    aria-current={active ? "true" : undefined}
                    className={cn("flex items-start gap-3 rounded-[16px] bg-[var(--feed-card)] p-3 text-foreground outline-none transition-colors hover:bg-[var(--feed-control)] focus-visible:ring-2 focus-visible:ring-ring", active && "bg-[var(--feed-control)]")}
                    data-newsroom-inbox-item="assignment"
                    data-newsroom-list-row
                    data-selected={active || undefined}
                    href={href}
                    key={assignment.id}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{assignment.title}</p>
                      <p className="text-xs text-muted-foreground">Assignment · {assignment.assignmentTypeKey}</p>
                    </div>
                    <span className="mt-0.5 shrink-0 rounded-full bg-[var(--feed-control)] px-2 py-0.5 text-xs font-medium">{assignment.status}</span>
                  </Link>
                );
              })}
            </div>
          </section>
        ) : null}

        {desks.length ? (
          <section aria-label="Sections" className="space-y-3" data-newsroom-ops-desks>
            <h2 className="text-sm font-medium text-muted-foreground">Sections</h2>
            {coreDesks.length ? <h3 className="newsroom-desk-group-heading" data-newsroom-ops-desk-group="core">Core sections</h3> : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {coreDesks.map((section) => (
                <Link
                  className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  data-newsroom-ops-desk={section.id}
                  href={buildNewsroomSectionHref(section.id, demo)}
                  key={section.id}
                >
                  <Card className="h-full rounded-[20px] border-0 bg-[var(--feed-card)] shadow-none ring-0 transition-colors hover:bg-[var(--feed-control)]">
                    <CardHeader className="p-4">
                      <CardTitle className="text-base font-semibold">{section.title}</CardTitle>
                      <CardDescription className="uppercase tracking-wide text-[0.65rem]">
                        {displayNewsroomSectionShortTitle(section)}
                      </CardDescription>
                    </CardHeader>
                  </Card>
                </Link>
              ))}
            </div>
            {rotatingDesks.length ? <h3 className="newsroom-desk-group-heading" data-newsroom-ops-desk-group="rotating">Rotating sections <small>appear for a while, then rotate out</small></h3> : null}
            {rotatingDesks.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {rotatingDesks.map((section) => (
                <Link
                  className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  data-newsroom-ops-desk={section.id}
                  href={buildNewsroomSectionHref(section.id, demo)}
                  key={section.id}
                >
                  <Card className="h-full rounded-[20px] border-0 bg-[var(--feed-card)] shadow-none ring-0 transition-colors hover:bg-[var(--feed-control)]">
                    <CardHeader className="p-4">
                      <CardTitle className="text-base font-semibold">{section.title}</CardTitle>
                      <CardDescription className="uppercase tracking-wide text-[0.65rem]">
                        {displayNewsroomSectionShortTitle(section)}
                      </CardDescription>
                    </CardHeader>
                  </Card>
                </Link>
              ))}
            </div> : null}
          </section>
        ) : null}
    </div>
  );

  return (
    <div
      className="h-full font-sans"
      data-news-desk-section="overview"
      data-newsroom-ops-home="true"
    >
      <div className="h-full" data-newsroom-overview-feeds>
        <div className="h-full" data-newsroom-overview-notifications>
          <NotificationCenter
            below={below}
            actorLabel={actorLabel}
            decisions={shownDecisions}
            demo={demo}
            fixture={notificationFixture}
            humanCuratedReferenceLineageIds={humanCuratedReferenceLineageIds}
            onCorrectCapture={onCorrectCapture}
            onRateReference={rateReference}
            referenceAttachments={referenceAttachments}
            predictionLoading={predictionState === "loading"}
            previews={previews}
            referenceDisabledReason={rateDisabled}
            references={canonicalReferences}
            referencesLoading={loading && !canonicalReferences.length}
          />
        </div>
      </div>
    </div>
  );
}
