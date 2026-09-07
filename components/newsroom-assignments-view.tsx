"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AssignmentRecord } from "../lib/category-repository";
import type { AssignmentAction, AssignmentStatusFilter } from "../lib/newsroom-assignments";
import {
  assignmentListSubtitle,
  assignmentStatusBadgeVariant,
  assignmentStatusLabel,
  compareAssignments,
  filterAssignmentsByStatus,
  formatAssignmentListDate,
  formatAssignmentTypeLabel,
  selectedAssignmentById,
} from "../lib/newsroom-assignments";
import {
  effectiveAssignmentsIndexFilters,
  parseAssignmentIdFromNewsroomPathname,
  readAssignmentsIndexFilters,
  syncBrowserNewsroomIndexUrl,
} from "../lib/newsroom-index-filters";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { cn } from "../lib/utils";

export type AssignmentDeskViewMode = "queue" | "budget";

export type ReportingPacketReviewDecision = "select" | "merge" | "brief" | "hold" | "kill";

export type ReportingPacketDecisionSummary = {
  decision: ReportingPacketReviewDecision;
  copywritingAssignmentId?: string | null;
  copywritingStatus?: string | null;
  draftItemId?: string | null;
  eventId: string;
  note?: string | null;
  targetItemId?: string | null;
};

type NewsroomAssignmentsViewProps = {
  assignments: AssignmentRecord[];
  budgetPanel?: ReactNode;
  demo?: boolean;
  disabled?: boolean;
  footerLabel?: string | null;
  hasMore?: boolean;
  initialAssignmentId?: string | null;
  initialView?: AssignmentDeskViewMode;
  isLoadingMore?: boolean;
  onAction: (assignment: AssignmentRecord, action: AssignmentAction, note?: string) => void;
  onLoadMore?: () => void;
  onReviewReportingPacket?: (
    assignment: AssignmentRecord,
    decision: ReportingPacketReviewDecision,
    note?: string,
    targetItemId?: string,
  ) => void;
  renderAssignmentDetailExtras?: (assignment: AssignmentRecord) => ReactNode;
  reportingDecisionForAssignment?: (assignmentId: string) => ReportingPacketDecisionSummary | null;
  reportingPacketSummaryForAssignment?: (assignment: AssignmentRecord) => string | null;
};

const STATUS_FILTERS: Array<{ key: AssignmentStatusFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "claimed", label: "Claimed" },
  { key: "completed", label: "Completed" },
  { key: "canceled", label: "Canceled" },
];

function buildAssignmentDetailPath(assignmentId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/assignments/${encodeURIComponent(assignmentId)}`, demo);
}

function AssignmentDetailPanel({
  assignment,
  disabled,
  note,
  onAction,
  onClose,
  onNoteChange,
  onReviewReportingPacket,
  onReportingMergeTargetChange,
  reportingDecision,
  reportingMergeTargetItemId,
  reportingPacketSummary,
  detailExtras,
}: {
  assignment: AssignmentRecord;
  disabled?: boolean;
  note: string;
  onAction: (action: AssignmentAction) => void;
  onClose?: () => void;
  onNoteChange: (note: string) => void;
  onReviewReportingPacket?: (decision: ReportingPacketReviewDecision) => void;
  onReportingMergeTargetChange: (value: string) => void;
  reportingDecision: ReportingPacketDecisionSummary | null;
  reportingMergeTargetItemId: string;
  reportingPacketSummary: string | null;
  detailExtras?: ReactNode;
}) {
  const terminal = assignment.status === "completed" || assignment.status === "canceled";
  const isReporting = assignment.assignmentTypeKey === "reporting.edition-candidate";

  return (
    <div
      className="flex h-full flex-col font-sans"
      data-news-desk-assignment-detail={assignment.id}
    >
      <article
        className={`news-desk-assignment-row${terminal ? " news-desk-assignment-row--terminal" : ""}`}
        data-assignment-candidate={assignment.id}
        data-assignment-id={assignment.id}
        data-assignment-status={assignment.status}
        data-reporting-decision={reportingDecision?.decision ?? ""}
      >
        <div className="space-y-4 p-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={assignmentStatusBadgeVariant(assignment.status)}>
                {assignmentStatusLabel(assignment.status)}
              </Badge>
              <Badge variant="outline">{formatAssignmentTypeLabel(assignment.assignmentTypeKey)}</Badge>
              {assignment.sectionKey ? (
                <Badge variant="outline">{assignment.sectionKey}</Badge>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">{assignment.assignmentTypeKey}</p>
            <h2 className="text-lg font-semibold leading-snug text-foreground">{assignment.title}</h2>
            {assignment.summary ? (
              <p className="text-sm text-muted-foreground">{assignment.summary}</p>
            ) : null}
          </div>

          <div className="flex flex-wrap gap-2" data-news-desk-assignment-actions>
            {assignment.status === "open" ? (
              <Button
                data-news-desk-assignment-claim
                disabled={disabled}
                onClick={() => onAction("claim")}
                size="sm"
                type="button"
              >
                Claim
              </Button>
            ) : null}
            {assignment.status === "claimed" ? (
              <Button
                data-news-desk-assignment-release
                disabled={disabled}
                onClick={() => onAction("release")}
                size="sm"
                type="button"
                variant="outline"
              >
                Release
              </Button>
            ) : null}
            {!terminal ? (
              <>
                <Button
                  data-news-desk-assignment-complete
                  disabled={disabled}
                  onClick={() => onAction("complete")}
                  size="sm"
                  type="button"
                >
                  Complete
                </Button>
                <Button
                  data-news-desk-assignment-cancel
                  disabled={disabled}
                  onClick={() => onAction("cancel")}
                  size="sm"
                  type="button"
                  variant="destructive"
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                data-news-desk-assignment-reopen
                disabled={disabled}
                onClick={() => onAction("reopen")}
                size="sm"
                type="button"
                variant="outline"
              >
                Reopen
              </Button>
            )}
          </div>

          {isReporting && reportingPacketSummary ? (
            <div className="space-y-2 rounded-xl border border-border bg-muted/20 p-3" data-reporting-packet-review>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Reporting packet</p>
              <p className="text-sm text-foreground">{reportingPacketSummary}</p>
              {onReviewReportingPacket ? (
                <div className="flex flex-wrap gap-2">
                  <Button disabled={disabled} onClick={() => onReviewReportingPacket("select")} size="sm" type="button">
                    Select Packet
                  </Button>
                  <Button disabled={disabled} onClick={() => onReviewReportingPacket("brief")} size="sm" type="button" variant="outline">
                    Make Brief
                  </Button>
                  <Button disabled={disabled} onClick={() => onReviewReportingPacket("hold")} size="sm" type="button" variant="outline">
                    Hold Packet
                  </Button>
                  <Button disabled={disabled} onClick={() => onReviewReportingPacket("kill")} size="sm" type="button" variant="destructive">
                    Kill Packet
                  </Button>
                  <label className="flex w-full flex-col gap-1 text-xs text-muted-foreground">
                    <span>Merge target Item ID</span>
                    <input
                      className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
                      data-reporting-merge-target={assignment.id}
                      disabled={disabled}
                      onChange={(event) => onReportingMergeTargetChange(event.target.value)}
                      placeholder="Required only for Merge Packet"
                      value={reportingMergeTargetItemId}
                    />
                  </label>
                  <Button
                    disabled={disabled || !reportingMergeTargetItemId.trim()}
                    onClick={() => onReviewReportingPacket("merge")}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Merge Packet
                  </Button>
                </div>
              ) : null}
              {reportingDecision ? (
                <p className="text-xs text-muted-foreground">
                  Decision: {reportingDecision.decision}
                  {reportingDecision.copywritingAssignmentId ? (
                    <span data-reporting-copywriting-assignment={reportingDecision.copywritingAssignmentId}>
                      {" "}· copywriting {reportingDecision.copywritingAssignmentId}
                    </span>
                  ) : null}
                  {reportingDecision.draftItemId ? (
                    <span data-reporting-draft-item={reportingDecision.draftItemId}>
                      {" "}· draft {reportingDecision.draftItemId}
                    </span>
                  ) : null}
                </p>
              ) : null}
            </div>
          ) : null}

          <Separator />

          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Queue</dt>
              <dd className="mt-1 text-foreground">{assignment.queueKey}</dd>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Assignee</dt>
                <dd className="mt-1 text-foreground">{assignment.assigneeKey ?? assignment.assigneeType ?? "Unassigned"}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Updated</dt>
                <dd className="mt-1 text-foreground">{formatAssignmentListDate(assignment)}</dd>
              </div>
            </div>
          </dl>

          <label className="block space-y-1.5 text-sm">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Note</span>
            <textarea
              className="min-h-16 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              data-assignment-reason={assignment.id}
              disabled={disabled}
              onChange={(event) => onNoteChange(event.target.value)}
              rows={2}
              value={note}
            />
          </label>

          {detailExtras}
        </div>
      </article>

      {onClose ? (
        <div className="border-t border-border p-4">
          <Button className="w-full" onClick={onClose} type="button" variant="secondary">
            Close
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function NewsroomAssignmentsView({
  assignments,
  budgetPanel,
  demo = false,
  disabled = false,
  footerLabel,
  hasMore = false,
  initialAssignmentId = null,
  initialView = "queue",
  isLoadingMore = false,
  onAction,
  onLoadMore,
  onReviewReportingPacket,
  renderAssignmentDetailExtras,
  reportingDecisionForAssignment,
  reportingPacketSummaryForAssignment,
}: NewsroomAssignmentsViewProps) {
  const pathname = usePathname();
  const pathnameAssignmentId = useMemo(
    () => parseAssignmentIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeAssignmentId = initialAssignmentId ?? pathnameAssignmentId ?? "";

  const [viewMode, setViewMode] = useState<AssignmentDeskViewMode>(initialView);
  const [statusFilter, setStatusFilter] = useState<AssignmentStatusFilter>(() => {
    if (typeof window === "undefined") return "all";
    const filters = readAssignmentsIndexFilters(new URLSearchParams(window.location.search));
    const status = filters.status?.trim();
    if (status === "open" || status === "claimed" || status === "completed" || status === "canceled") {
      return status;
    }
    return "all";
  });
  const [selectedAssignmentId, setSelectedAssignmentId] = useState(routeAssignmentId);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(Boolean(routeAssignmentId));
  const [actionNote, setActionNote] = useState("");
  const [reportingMergeTargetItemId, setReportingMergeTargetItemId] = useState("");

  const sortedAssignments = useMemo(
    () => [...assignments].sort(compareAssignments),
    [assignments],
  );
  const statusCounts = useMemo(() => {
    const counts: Record<AssignmentStatusFilter, number> = {
      all: sortedAssignments.length,
      open: 0,
      claimed: 0,
      completed: 0,
      canceled: 0,
    };
    for (const assignment of sortedAssignments) {
      const status = assignment.status as AssignmentStatusFilter;
      if (status in counts && status !== "all") counts[status] += 1;
    }
    return counts;
  }, [sortedAssignments]);

  const filteredAssignments = useMemo(
    () => filterAssignmentsByStatus(sortedAssignments, statusFilter),
    [sortedAssignments, statusFilter],
  );

  const selectedAssignment = useMemo(
    () => selectedAssignmentById(filteredAssignments, selectedAssignmentId)
      ?? selectedAssignmentById(sortedAssignments, selectedAssignmentId),
    [filteredAssignments, selectedAssignmentId, sortedAssignments],
  );

  const selectedIndex = selectedAssignment
    ? filteredAssignments.findIndex((entry) => entry.id === selectedAssignment.id)
    : -1;
  const previousAssignment = selectedIndex > 0 ? filteredAssignments[selectedIndex - 1] : null;
  const nextAssignment = selectedIndex >= 0 && selectedIndex < filteredAssignments.length - 1
    ? filteredAssignments[selectedIndex + 1]
    : null;

  const syncStatusUrl = useCallback((nextStatus: AssignmentStatusFilter, nextView: AssignmentDeskViewMode) => {
    if (demo) return;
    syncBrowserNewsroomIndexUrl("assignments", effectiveAssignmentsIndexFilters({
      status: nextStatus === "all" ? "" : nextStatus,
      type: "",
      view: nextView === "budget" ? "budget" : "queue",
    }), { replace: true });
  }, [demo]);

  useEffect(() => {
    if (!routeAssignmentId) return;
    setSelectedAssignmentId(routeAssignmentId);
    setMobileDetailOpen(true);
  }, [routeAssignmentId]);

  useEffect(() => {
    setActionNote("");
    setReportingMergeTargetItemId("");
  }, [selectedAssignment?.id, selectedAssignment?.status]);

  const selectAssignment = (assignmentId: string) => {
    setSelectedAssignmentId(assignmentId);
    setMobileDetailOpen(true);
    if (typeof window !== "undefined") {
      const nextPath = buildAssignmentDetailPath(assignmentId, demo);
      if (`${window.location.pathname}${window.location.search}` !== nextPath) {
        window.history.pushState(null, "", nextPath);
      }
    }
  };

  const closeDetail = () => {
    setMobileDetailOpen(false);
    setSelectedAssignmentId("");
    if (typeof window !== "undefined") {
      const indexPath = getNewsroomNavHref("/newsroom/assignments", demo);
      window.history.replaceState(null, "", indexPath);
    }
  };

  const runAction = (action: AssignmentAction) => {
    if (!selectedAssignment) return;
    onAction(selectedAssignment, action, actionNote);
    setActionNote("");
  };

  const runReportingReview = (decision: ReportingPacketReviewDecision) => {
    if (!selectedAssignment || !onReviewReportingPacket) return;
    onReviewReportingPacket(selectedAssignment, decision, actionNote, reportingMergeTargetItemId);
    setActionNote("");
  };

  const selectViewMode = (nextView: AssignmentDeskViewMode) => {
    setViewMode(nextView);
    syncStatusUrl(statusFilter, nextView);
  };

  const emptyLabel = sortedAssignments.length
    ? "No assignments match this filter."
    : "No assignments in the queue yet.";

  const reportingDecision = selectedAssignment && reportingDecisionForAssignment
    ? reportingDecisionForAssignment(selectedAssignment.id)
    : null;
  const reportingPacketSummary = selectedAssignment && reportingPacketSummaryForAssignment
    ? reportingPacketSummaryForAssignment(selectedAssignment)
    : null;

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 font-sans md:flex-row"
      data-detail-open={selectedAssignment || routeAssignmentId ? "true" : "false"}
      data-news-desk-assignments
      data-news-desk-section="assignments"
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold tracking-tight">Assignments</h2>
            <p className="text-sm text-muted-foreground">
              Claim, complete, and review newsroom work from the private queue.
            </p>
          </div>
          <div className="flex gap-1 rounded-lg border border-border bg-muted/30 p-1" role="group" aria-label="Assignment view">
            <Button
              data-active={viewMode === "queue" || undefined}
              onClick={() => selectViewMode("queue")}
              size="sm"
              type="button"
              variant={viewMode === "queue" ? "default" : "ghost"}
            >
              Queue
            </Button>
            <Button
              data-active={viewMode === "budget" || undefined}
              onClick={() => selectViewMode("budget")}
              size="sm"
              type="button"
              variant={viewMode === "budget" ? "default" : "ghost"}
            >
              Story Budget
            </Button>
          </div>
        </div>

        {viewMode === "budget" ? (
          <div className="min-h-0 flex-1">{budgetPanel}</div>
        ) : (
          <>
            <Tabs
              defaultValue="all"
              onValueChange={(value) => {
                const next = value as AssignmentStatusFilter;
                setStatusFilter(next);
                syncStatusUrl(next, viewMode);
              }}
              value={statusFilter}
            >
              <TabsList className="h-auto w-full flex-wrap justify-start gap-1 bg-muted/40 p-1">
                {STATUS_FILTERS.map((filter) => (
                  <TabsTrigger className="text-xs sm:text-sm" key={filter.key} value={filter.key}>
                    {filter.label}
                    <Badge className="ml-1.5 min-w-5 px-1.5" variant="secondary">
                      {statusCounts[filter.key]}
                    </Badge>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            <ScrollArea className="min-h-0 flex-1 md:max-h-[calc(100dvh-16rem)]">
              <div className="flex flex-col gap-2 pb-4" data-newsroom-card-grid>
                {filteredAssignments.length ? filteredAssignments.map((assignment) => {
                  const active = selectedAssignmentId === assignment.id;
                  return (
                    <button
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "w-full rounded-xl border bg-card p-4 text-left transition-colors",
                        active ? "border-primary ring-2 ring-primary/20" : "border-border hover:border-primary/30",
                      )}
                      data-assignment-candidate={assignment.id}
                      data-assignment-status={assignment.status}
                      data-newsroom-card
                      data-newsroom-card-id={assignment.id}
                      key={assignment.id}
                      onClick={() => selectAssignment(assignment.id)}
                      type="button"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1 space-y-1">
                          <p className="truncate text-sm font-medium text-foreground">{assignment.title}</p>
                          <p className="truncate text-xs text-muted-foreground">{assignmentListSubtitle(assignment)}</p>
                        </div>
                        <Badge variant={assignmentStatusBadgeVariant(assignment.status)}>
                          {assignmentStatusLabel(assignment.status)}
                        </Badge>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">{formatAssignmentListDate(assignment)}</p>
                    </button>
                  );
                }) : (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">No assignments</CardTitle>
                      <CardDescription>{emptyLabel}</CardDescription>
                    </CardHeader>
                  </Card>
                )}
              </div>
              {footerLabel ? (
                <p className="px-1 pb-2 text-xs text-muted-foreground">{footerLabel}</p>
              ) : null}
              {hasMore && onLoadMore ? (
                <div className="pb-4">
                  <Button disabled={isLoadingMore} onClick={onLoadMore} type="button" variant="outline">
                    {isLoadingMore ? "Loading…" : "Load more"}
                  </Button>
                </div>
              ) : null}
            </ScrollArea>
          </>
        )}
      </div>

      {viewMode === "queue" ? (
        <div
          className="hidden min-h-0 w-full shrink-0 flex-col rounded-xl border border-border bg-card md:flex md:w-[min(100%,24rem)] lg:w-[min(100%,28rem)]"
          data-detail-open={selectedAssignment ? "true" : "false"}
          data-newsroom-list-detail-shell
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <span className="text-sm font-medium text-foreground">Detail</span>
            <div className="newsroom-list-detail-shell__detail-toolbar-trailing flex items-center gap-1">
              <Button
                aria-label="Previous"
                disabled={!previousAssignment}
                onClick={() => previousAssignment && selectAssignment(previousAssignment.id)}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <ChevronLeftIcon className="size-4" />
              </Button>
              <Button
                aria-label="Next"
                disabled={!nextAssignment}
                onClick={() => nextAssignment && selectAssignment(nextAssignment.id)}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <ChevronRightIcon className="size-4" />
              </Button>
            </div>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            {selectedAssignment ? (
              <AssignmentDetailPanel
                assignment={selectedAssignment}
                detailExtras={renderAssignmentDetailExtras?.(selectedAssignment)}
                disabled={disabled}
                note={actionNote}
                onAction={runAction}
                onNoteChange={setActionNote}
                onReportingMergeTargetChange={setReportingMergeTargetItemId}
                onReviewReportingPacket={onReviewReportingPacket ? runReportingReview : undefined}
                reportingDecision={reportingDecision}
                reportingMergeTargetItemId={reportingMergeTargetItemId}
                reportingPacketSummary={reportingPacketSummary}
              />
            ) : (
              <CardContent className="p-4 text-sm text-muted-foreground">
                Select an assignment to inspect work details.
              </CardContent>
            )}
          </ScrollArea>
        </div>
      ) : null}

      <Sheet onOpenChange={(open) => {
        if (!open) closeDetail();
        else setMobileDetailOpen(true);
      }} open={mobileDetailOpen && Boolean(selectedAssignment) && viewMode === "queue"}>
        <SheetContent className="gap-0 p-0 md:hidden" side="bottom">
          <SheetHeader className="border-b border-border px-4 py-3">
            <SheetTitle className="text-left text-base">Assignment</SheetTitle>
          </SheetHeader>
          {selectedAssignment ? (
            <ScrollArea className="max-h-[75dvh]">
              <AssignmentDetailPanel
                assignment={selectedAssignment}
                detailExtras={renderAssignmentDetailExtras?.(selectedAssignment)}
                disabled={disabled}
                note={actionNote}
                onAction={runAction}
                onClose={closeDetail}
                onNoteChange={setActionNote}
                onReportingMergeTargetChange={setReportingMergeTargetItemId}
                onReviewReportingPacket={onReviewReportingPacket ? runReportingReview : undefined}
                reportingDecision={reportingDecision}
                reportingMergeTargetItemId={reportingMergeTargetItemId}
                reportingPacketSummary={reportingPacketSummary}
              />
            </ScrollArea>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
