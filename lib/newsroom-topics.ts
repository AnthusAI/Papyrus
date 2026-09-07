import type { CategorySteeringProposal } from "./category-repository";

export type TopicProposalReviewAction = "accept" | "reject" | "defer" | "edit";

export type TopicProposalStatusFilter = "all" | "proposed" | "deferred" | "reviewed";

const TOPIC_PROPOSAL_BLOCKED_APPLY_KINDS = new Set([
  "merge-category",
  "merge-categories",
  "split-category",
  "archive-category",
  "deprecate-category",
]);

export function isCategoryTopicProposal(proposal: CategorySteeringProposal): boolean {
  return proposal.steeringDomain === "category";
}

export function filterTopicProposals(
  proposals: CategorySteeringProposal[],
  statusFilter: TopicProposalStatusFilter,
): CategorySteeringProposal[] {
  const categoryProposals = proposals.filter(isCategoryTopicProposal);
  if (statusFilter === "all") return categoryProposals;
  if (statusFilter === "reviewed") {
    return categoryProposals.filter((proposal) => (
      proposal.status === "accepted" || proposal.status === "rejected"
    ));
  }
  return categoryProposals.filter((proposal) => proposal.status === statusFilter);
}

export function countTopicProposalsByStatus(
  proposals: CategorySteeringProposal[],
): Record<TopicProposalStatusFilter, number> {
  const categoryProposals = proposals.filter(isCategoryTopicProposal);
  return {
    all: categoryProposals.length,
    proposed: categoryProposals.filter((proposal) => proposal.status === "proposed").length,
    deferred: categoryProposals.filter((proposal) => proposal.status === "deferred").length,
    reviewed: categoryProposals.filter((proposal) => (
      proposal.status === "accepted" || proposal.status === "rejected"
    )).length,
  };
}

export function compareTopicProposals(
  left: CategorySteeringProposal,
  right: CategorySteeringProposal,
): number {
  const statusWeight = new Map([
    ["proposed", 0],
    ["deferred", 1],
    ["accepted", 2],
    ["rejected", 3],
  ]);
  const statusDiff = (statusWeight.get(left.status) ?? 9) - (statusWeight.get(right.status) ?? 9);
  if (statusDiff !== 0) return statusDiff;
  const dateDiff = (right.proposedAt ?? right.updatedAt ?? "").localeCompare(left.proposedAt ?? left.updatedAt ?? "");
  if (dateDiff !== 0) return dateDiff;
  return proposalDisplayTitle(left).localeCompare(proposalDisplayTitle(right));
}

export function sortTopicProposals(proposals: CategorySteeringProposal[]): CategorySteeringProposal[] {
  return [...proposals].sort(compareTopicProposals);
}

export function proposalDisplayTitle(proposal: CategorySteeringProposal): string {
  return proposal.displayName?.trim() || proposal.title?.trim() || proposal.categoryKey || proposal.id;
}

export function proposalStatusLabel(status: string): string {
  if (status === "accepted") return "Accepted";
  if (status === "rejected") return "Rejected";
  if (status === "deferred") return "Deferred";
  return "Proposed";
}

export function proposalStatusBadgeVariant(
  status: string,
): "default" | "secondary" | "outline" | "muted" {
  if (status === "accepted") return "default";
  if (status === "rejected") return "outline";
  if (status === "deferred") return "secondary";
  return "muted";
}

export function formatProposalListDate(proposal: CategorySteeringProposal): string {
  const value = proposal.proposedAt ?? proposal.reviewedAt ?? proposal.updatedAt ?? "";
  if (!value) return "Undated";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(timestamp));
}

export function selectedTopicProposalById(
  proposals: CategorySteeringProposal[],
  proposalId: string | null | undefined,
): CategorySteeringProposal | null {
  if (!proposalId) return null;
  return proposals.find((proposal) => proposal.id === proposalId) ?? null;
}

export function topicProposalReviewBlockedReason(
  proposal: CategorySteeringProposal,
  action: TopicProposalReviewAction,
): string | null {
  if ((action === "accept" || action === "edit") && TOPIC_PROPOSAL_BLOCKED_APPLY_KINDS.has(proposal.proposalKind)) {
    return `${proposal.proposalKind} apply is not implemented yet.`;
  }
  return null;
}

