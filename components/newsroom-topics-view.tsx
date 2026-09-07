"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  PencilIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { CategorySteeringProposal } from "../lib/category-repository";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { newsroomListRowClassName } from "../lib/newsroom-list-selection";
import {
  countTopicProposalsByStatus,
  filterTopicProposals,
  formatProposalListDate,
  proposalDisplayTitle,
  proposalStatusBadgeVariant,
  proposalStatusLabel,
  selectedTopicProposalById,
  sortTopicProposals,
  topicProposalReviewBlockedReason,
  type TopicProposalReviewAction,
  type TopicProposalStatusFilter,
} from "../lib/newsroom-topics";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { ScrollArea } from "./ui/scroll-area";
import { Separator } from "./ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "./ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

type NewsroomTopicsViewProps = {
  demo?: boolean;
  disabled?: boolean;
  initialProposalId?: string | null;
  onEdit: (proposal: CategorySteeringProposal) => void;
  onReview: (proposal: CategorySteeringProposal, action: TopicProposalReviewAction) => void;
  proposals: CategorySteeringProposal[];
};

const STATUS_FILTERS: Array<{ key: TopicProposalStatusFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "proposed", label: "Proposed" },
  { key: "deferred", label: "Deferred" },
  { key: "reviewed", label: "Reviewed" },
];

function buildTopicsDetailPath(proposalId: string, demo?: boolean): string {
  const base = `/newsroom/topics?proposal=${encodeURIComponent(proposalId)}`;
  return getNewsroomNavHref(base, demo);
}

function TopicProposalDetailPanel({
  disabled,
  onClose,
  onEdit,
  onReview,
  proposal,
}: {
  disabled?: boolean;
  onClose?: () => void;
  onEdit: () => void;
  onReview: (action: TopicProposalReviewAction) => void;
  proposal: CategorySteeringProposal;
}) {
  const acceptBlockedReason = topicProposalReviewBlockedReason(proposal, "accept");
  const editBlockedReason = topicProposalReviewBlockedReason(proposal, "edit");
  const acceptDisabled = disabled || proposal.status === "accepted" || Boolean(acceptBlockedReason);
  const rejectDisabled = disabled || proposal.status === "rejected";
  const deferDisabled = disabled || proposal.status === "deferred";
  const editDisabled = disabled || proposal.status === "accepted" || Boolean(editBlockedReason);

  return (
    <div
      className="flex h-full flex-col font-sans"
      data-news-desk-topic-proposal-detail={proposal.id}
      data-news-desk-proposed-subcategory={proposal.categoryKey ?? undefined}
    >
      <div className="space-y-4 p-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={proposalStatusBadgeVariant(proposal.status)}>
              {proposalStatusLabel(proposal.status)}
            </Badge>
            <Badge variant="outline">{proposal.proposalKind}</Badge>
            {proposal.targetCategoryKey ? (
              <Badge variant="outline">{proposal.targetCategoryKey}</Badge>
            ) : null}
          </div>
          <h2 className="text-lg font-semibold leading-snug text-foreground">
            {proposalDisplayTitle(proposal)}
          </h2>
          {proposal.summary ? (
            <p className="text-sm text-muted-foreground">{proposal.summary}</p>
          ) : null}
        </div>

        <div
          aria-label={`${proposal.title} review actions`}
          className="category-steering-proposal__actions flex flex-wrap items-center gap-2"
          data-news-desk-topic-review-cluster
        >
          <Button
            aria-label="Accept proposal"
            aria-pressed={proposal.status === "accepted"}
            data-review-action="accept"
            disabled={acceptDisabled}
            onClick={() => onReview("accept")}
            size="sm"
            title={acceptBlockedReason ?? undefined}
            type="button"
            variant={proposal.status === "accepted" ? "default" : "outline"}
          >
            <ThumbsUpIcon className="size-4" />
            Accept
          </Button>
          <Button
            aria-label="Reject proposal"
            aria-pressed={proposal.status === "rejected"}
            data-review-action="reject"
            disabled={rejectDisabled}
            onClick={() => onReview("reject")}
            size="sm"
            type="button"
            variant={proposal.status === "rejected" ? "destructive" : "outline"}
          >
            <ThumbsDownIcon className="size-4" />
            Reject
          </Button>
          <Button
            aria-label="Defer proposal"
            aria-pressed={proposal.status === "deferred"}
            data-review-action="defer"
            disabled={deferDisabled}
            onClick={() => onReview("defer")}
            size="sm"
            type="button"
            variant="outline"
          >
            Defer
          </Button>
          <Button
            aria-label="Edit proposal"
            data-review-action="edit"
            disabled={editDisabled}
            onClick={onEdit}
            size="sm"
            title={editBlockedReason ?? undefined}
            type="button"
            variant="outline"
          >
            <PencilIcon className="size-4" />
            Edit
          </Button>
        </div>

        <Separator />

        <dl className="grid gap-3 text-sm">
          {proposal.description ? (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Description</dt>
              <dd className="mt-1 text-foreground">{proposal.description}</dd>
            </div>
          ) : null}
          {proposal.categoryKey ? (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Category key</dt>
              <dd className="mt-1 font-mono text-xs text-foreground">{proposal.categoryKey}</dd>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Proposed</dt>
              <dd className="mt-1 text-foreground">{formatProposalListDate(proposal)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Evidence</dt>
              <dd className="mt-1 text-foreground">
                {proposal.evidenceItemIds?.filter(Boolean).length ?? 0} refs
              </dd>
            </div>
          </div>
        </dl>

        {onClose ? (
          <Button className="w-full" onClick={onClose} type="button" variant="secondary">
            Close
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function NewsroomTopicsView({
  demo = false,
  disabled = false,
  initialProposalId = null,
  onEdit,
  onReview,
  proposals,
}: NewsroomTopicsViewProps) {
  const sortedProposals = useMemo(() => sortTopicProposals(proposals), [proposals]);
  const statusCounts = useMemo(() => countTopicProposalsByStatus(sortedProposals), [sortedProposals]);

  const [statusFilter, setStatusFilter] = useState<TopicProposalStatusFilter>("proposed");
  const [selectedProposalId, setSelectedProposalId] = useState(initialProposalId ?? "");
  const [mobileDetailOpen, setMobileDetailOpen] = useState(Boolean(initialProposalId));

  const filteredProposals = useMemo(
    () => filterTopicProposals(sortedProposals, statusFilter),
    [sortedProposals, statusFilter],
  );

  const selectedProposal = useMemo(
    () => selectedTopicProposalById(filteredProposals, selectedProposalId)
      ?? selectedTopicProposalById(sortedProposals, selectedProposalId),
    [filteredProposals, selectedProposalId, sortedProposals],
  );

  const selectedIndex = selectedProposal
    ? filteredProposals.findIndex((entry) => entry.id === selectedProposal.id)
    : -1;
  const previousProposal = selectedIndex > 0 ? filteredProposals[selectedIndex - 1] : null;
  const nextProposal = selectedIndex >= 0 && selectedIndex < filteredProposals.length - 1
    ? filteredProposals[selectedIndex + 1]
    : null;

  useEffect(() => {
    if (!initialProposalId) return;
    setSelectedProposalId(initialProposalId);
    setMobileDetailOpen(true);
  }, [initialProposalId]);

  const selectProposal = useCallback((proposalId: string) => {
    setSelectedProposalId(proposalId);
    setMobileDetailOpen(true);
    if (typeof window !== "undefined") {
      const nextPath = buildTopicsDetailPath(proposalId, demo);
      if (`${window.location.pathname}${window.location.search}` !== nextPath) {
        window.history.pushState(null, "", nextPath);
      }
    }
  }, [demo]);

  const closeDetail = useCallback(() => {
    setMobileDetailOpen(false);
    setSelectedProposalId("");
    if (typeof window !== "undefined") {
      const indexPath = getNewsroomNavHref("/newsroom/topics", demo);
      window.history.replaceState(null, "", indexPath);
    }
  }, [demo]);

  const runReview = (action: TopicProposalReviewAction) => {
    if (!selectedProposal) return;
    if (action === "edit") {
      onEdit(selectedProposal);
      return;
    }
    onReview(selectedProposal, action);
  };

  const emptyLabel = sortedProposals.length
    ? "No topic proposals match this filter."
    : "No category steering proposals in the queue yet.";

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 font-sans md:flex-row"
      data-detail-open={selectedProposal || initialProposalId ? "true" : "false"}
      data-news-desk-section="topics"
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">Topics</h2>
          <p className="text-sm text-muted-foreground">
            Review taxonomy proposals before they shape accepted topic coverage.
          </p>
        </div>

        <Tabs
          defaultValue="proposed"
          onValueChange={(value) => setStatusFilter(value as TopicProposalStatusFilter)}
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
            {filteredProposals.length ? filteredProposals.map((proposal) => {
              const active = selectedProposalId === proposal.id;
              return (
                <button
                  aria-current={active ? "true" : undefined}
                  className={newsroomListRowClassName(active)}
                  data-newsroom-list-row
                  data-selected={active || undefined}
                  data-newsroom-card
                  data-newsroom-card-id={proposal.id}
                  data-topic-queue-proposal={proposal.id}
                  key={proposal.id}
                  onClick={() => selectProposal(proposal.id)}
                  type="button"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="truncate text-sm font-medium">{proposalDisplayTitle(proposal)}</p>
                      <p className="truncate text-xs text-muted-foreground">{proposal.proposalKind}</p>
                    </div>
                    <Badge variant={proposalStatusBadgeVariant(proposal.status)}>
                      {proposalStatusLabel(proposal.status)}
                    </Badge>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                    {proposal.summary ?? "No summary provided."}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">{formatProposalListDate(proposal)}</p>
                </button>
              );
            }) : (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">No proposals</CardTitle>
                  <CardDescription>{emptyLabel}</CardDescription>
                </CardHeader>
              </Card>
            )}
          </div>
        </ScrollArea>
      </div>

      <div
        className="hidden min-h-0 w-full shrink-0 flex-col rounded-xl border border-border bg-card md:flex md:w-[min(100%,24rem)] lg:w-[min(100%,28rem)]"
        data-detail-open={selectedProposal ? "true" : "false"}
        data-news-desk-section="topics"
        data-newsroom-list-detail-shell
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="text-sm font-medium text-foreground">Detail</span>
          <div className="newsroom-list-detail-shell__detail-toolbar-trailing flex items-center gap-1">
            <Button
              aria-label="Previous"
              disabled={!previousProposal}
              onClick={() => previousProposal && selectProposal(previousProposal.id)}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
            <Button
              aria-label="Next"
              disabled={!nextProposal}
              onClick={() => nextProposal && selectProposal(nextProposal.id)}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronRightIcon className="size-4" />
            </Button>
          </div>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          {selectedProposal ? (
            <TopicProposalDetailPanel
              disabled={disabled}
              onEdit={() => onEdit(selectedProposal)}
              onReview={(action) => onReview(selectedProposal, action)}
              proposal={selectedProposal}
            />
          ) : (
            <CardContent className="p-4 text-sm text-muted-foreground">
              Select a topic proposal to review steering changes.
            </CardContent>
          )}
        </ScrollArea>
      </div>

      <Sheet
        onOpenChange={(open) => {
          if (!open) closeDetail();
          else setMobileDetailOpen(true);
        }}
        open={mobileDetailOpen && Boolean(selectedProposal)}
      >
        <SheetContent className="gap-0 p-0 md:hidden" side="bottom">
          <SheetHeader className="border-b border-border px-4 py-3">
            <SheetTitle className="text-left text-base">Topic proposal</SheetTitle>
          </SheetHeader>
          {selectedProposal ? (
            <ScrollArea className="max-h-[75dvh]">
              <TopicProposalDetailPanel
                disabled={disabled}
                onClose={closeDetail}
                onEdit={() => onEdit(selectedProposal)}
                onReview={(action) => onReview(selectedProposal, action)}
                proposal={selectedProposal}
              />
            </ScrollArea>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
