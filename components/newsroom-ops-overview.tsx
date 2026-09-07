"use client";

import {
  BookOpenIcon,
  ClipboardListIcon,
  LayersIcon,
  MessageSquareIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { AssignmentRecord, MessageRecord, NewsroomSectionRecord, ReferenceRecord } from "../lib/category-repository";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import {
  countReferencesByStatus,
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
  sortNewsroomSections,
} from "../lib/newsroom-sections";
import { cn } from "../lib/utils";

type NewsroomOpsOverviewProps = {
  assignments: AssignmentRecord[];
  demo?: boolean;
  messages: MessageRecord[];
  newsroomSections: NewsroomSectionRecord[];
  references: ReferenceRecord[];
};

type DestinationKey = "references" | "assignments" | "messages" | "topics";

const DESTINATION_META: Record<DestinationKey, { label: string; detail: string; href: string; icon: typeof BookOpenIcon }> = {
  references: { label: "References", detail: "Source intake", href: "/newsroom/references", icon: BookOpenIcon },
  assignments: { label: "Assignments", detail: "Work queue", href: "/newsroom/assignments", icon: ClipboardListIcon },
  messages: { label: "Messages", detail: "Team threads", href: "/newsroom/messages", icon: MessageSquareIcon },
  topics: { label: "Topics", detail: "Taxonomy", href: "/newsroom/topics", icon: LayersIcon },
};

function openAssignmentCount(assignments: AssignmentRecord[]): number {
  return assignments.filter((assignment) => {
    const status = assignment.status?.trim().toLowerCase() ?? "";
    return status === "open" || status === "claimed" || status === "pending";
  }).length;
}

function recentMessageCount(messages: MessageRecord[]): number {
  return messages.filter((message) => message.status !== "archived").length;
}

export function NewsroomOpsOverview({
  assignments,
  demo = false,
  messages,
  newsroomSections,
  references,
}: NewsroomOpsOverviewProps) {
  const canonicalReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  const referenceCounts = useMemo(() => countReferencesByStatus(canonicalReferences), [canonicalReferences]);
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

  const destinationCounts: Record<DestinationKey, number | null> = {
    references: referenceCounts.pending ?? 0,
    assignments: openAssignmentCount(assignments),
    messages: recentMessageCount(messages),
    topics: null,
  };

  return (
    <div
      className="space-y-8 font-sans"
      data-news-desk-section="overview"
      data-newsroom-ops-home="true"
    >
      <div className="space-y-8" data-newsroom-overview-feeds>
        <section aria-label="Destinations" className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Go to</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(Object.keys(DESTINATION_META) as DestinationKey[]).map((key) => {
              const meta = DESTINATION_META[key];
              const Icon = meta.icon;
              const count = destinationCounts[key];
              const href = getNewsroomNavHref(meta.href, demo);
              return (
                <Link
                  className="group block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  data-newsroom-ops-destination={key}
                  data-newsroom-overview-section={key}
                  href={href}
                  key={key}
                >
                  <Card className="h-full transition-colors group-hover:border-primary/40">
                    <CardHeader className="space-y-3 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <Icon className="size-4" aria-hidden="true" />
                        </span>
                        {count != null && count > 0 ? (
                          <Badge variant="default">{count}</Badge>
                        ) : null}
                      </div>
                      <div className="space-y-0.5">
                        <CardTitle className="text-base font-semibold">{meta.label}</CardTitle>
                        <CardDescription>{meta.detail}</CardDescription>
                      </div>
                    </CardHeader>
                  </Card>
                </Link>
              );
            })}
          </div>
        </section>

        <section aria-label="Needs attention" className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Needs attention</h2>
          {pendingReferences.length || attentionAssignments.length ? (
            <div className="space-y-2">
              {pendingReferences.map((reference) => {
                const lineageId = referenceLineageId(reference);
                const href = getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo);
                return (
                  <Link
                    className="flex items-start gap-3 rounded-xl border border-border bg-card p-3 transition-colors hover:border-primary/30 hover:bg-muted/30"
                    data-newsroom-inbox-item="reference"
                    data-newsroom-card
                    data-newsroom-card-id={lineageId}
                    href={href}
                    key={lineageId}
                  >
                    <Badge className="mt-0.5 shrink-0" variant="outline">Pending</Badge>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{referenceDisplayTitle(reference)}</p>
                      <p className="text-xs text-muted-foreground">Review source intake · {formatReferenceListDate(reference)}</p>
                    </div>
                  </Link>
                );
              })}
              {attentionAssignments.map((assignment) => {
                const href = getNewsroomNavHref(`/newsroom/assignments/${encodeURIComponent(assignment.id)}`, demo);
                return (
                  <Link
                    className="flex items-start gap-3 rounded-xl border border-border bg-card p-3 transition-colors hover:border-primary/30 hover:bg-muted/30"
                    data-newsroom-inbox-item="assignment"
                    href={href}
                    key={assignment.id}
                  >
                    <Badge className="mt-0.5 shrink-0" variant="secondary">{assignment.status}</Badge>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{assignment.title}</p>
                      <p className="text-xs text-muted-foreground">Assignment · {assignment.assignmentTypeKey}</p>
                    </div>
                  </Link>
                );
              })}
            </div>
          ) : (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                Nothing needs attention right now. Check References for new intake or open Assignments from the destinations above.
              </CardContent>
            </Card>
          )}
        </section>

        {desks.length ? (
          <section aria-label="Desks" className="space-y-3" data-newsroom-ops-desks>
            <h2 className="text-sm font-medium text-muted-foreground">Desks</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {desks.map((section) => (
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
          </section>
        ) : null}
      </div>
    </div>
  );
}
