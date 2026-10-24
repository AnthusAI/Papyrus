"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { AssignmentRecord, NewsroomSectionRecord, ReferenceRecord } from "../lib/category-repository";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import {
  filterReferencesByStatus,
  formatReferenceListDate,
  referenceDisplayTitle,
  referenceLineageId,
  selectCanonicalReferenceRecords,
} from "../lib/newsroom-references";
import {
  buildNewsroomSectionHref,
  displayNewsroomSectionShortTitle,
  isEnabledNewsroomSection,
  newsroomDeskKind,
  sortNewsroomSections,
} from "../lib/newsroom-sections";
import { newsroomInboxRowClassName } from "../lib/newsroom-list-selection";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { NotificationCenter } from "./notification-center";

type NewsroomOpsOverviewProps = {
  assignments: AssignmentRecord[];
  actorLabel?: string;
  decisions?: ReadonlyMap<string, RelevanceDecisionView>;
  demo?: boolean;
  humanCuratedReferenceLineageIds?: ReadonlySet<string>;
  newsroomSections: NewsroomSectionRecord[];
  references: ReferenceRecord[];
};

const NO_DECISIONS: ReadonlyMap<string, RelevanceDecisionView> = new Map();
const NO_IDS: ReadonlySet<string> = new Set();

export function NewsroomOpsOverview({
  actorLabel = "",
  assignments,
  decisions = NO_DECISIONS,
  demo = false,
  humanCuratedReferenceLineageIds = NO_IDS,
  newsroomSections,
  references,
}: NewsroomOpsOverviewProps) {
  const pathname = usePathname();
  const canonicalReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  const pendingReferences = useMemo(
    () => filterReferencesByStatus(canonicalReferences, "pending").slice(0, 5),
    [canonicalReferences],
  );
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

  return (
    <div
      className="space-y-8 font-sans"
      data-news-desk-section="overview"
      data-newsroom-ops-home="true"
    >
      <div className="space-y-8" data-newsroom-overview-feeds>
        <div aria-label="Notification Center feed" className="newsroom-overview-feed-frame rounded-xl border bg-card p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" data-newsroom-overview-notifications role="region" tabIndex={0}>
          <NotificationCenter
            actorLabel={actorLabel}
            decisions={decisions}
            demo={demo}
            humanCuratedReferenceLineageIds={humanCuratedReferenceLineageIds}
            references={canonicalReferences}
          />
        </div>
        <section aria-label="Needs attention" className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Needs attention</h2>
          {pendingReferences.length || attentionAssignments.length ? (
            <div className="space-y-2">
              {pendingReferences.map((reference) => {
                const lineageId = referenceLineageId(reference);
                const href = getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo);
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    aria-current={active ? "true" : undefined}
                    className={newsroomInboxRowClassName(active)}
                    data-newsroom-inbox-item="reference"
                    data-newsroom-list-row
                    data-selected={active || undefined}
                    data-newsroom-card
                    data-newsroom-card-id={lineageId}
                    href={href}
                    key={lineageId}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{referenceDisplayTitle(reference)}</p>
                      <p className="text-xs text-muted-foreground">Review source intake · {formatReferenceListDate(reference)}</p>
                    </div>
                    <Badge className="mt-0.5 shrink-0" variant="outline">Pending</Badge>
                  </Link>
                );
              })}
              {attentionAssignments.map((assignment) => {
                const href = getNewsroomNavHref(`/newsroom/assignments/${encodeURIComponent(assignment.id)}`, demo);
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    aria-current={active ? "true" : undefined}
                    className={newsroomInboxRowClassName(active)}
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
                    <Badge className="mt-0.5 shrink-0" variant="secondary">{assignment.status}</Badge>
                  </Link>
                );
              })}
            </div>
          ) : (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                No pending references or open assignments. Check those destinations for other work.
              </CardContent>
            </Card>
          )}
        </section>

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
                  <Card className="h-full transition-colors hover:border-primary/30">
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
                  <Card className="h-full transition-colors hover:border-primary/30">
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
    </div>
  );
}
