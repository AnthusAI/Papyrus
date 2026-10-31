/**
 * The newsroom, as the linked editor sees it: their site's AppSync API, called with THEIR OWN Cognito access token (the one
 * Alexa account linking issued). AppSync checks the editor and admin groups exactly as it does for the web newsroom, and a vote
 * is recorded as the editor's human vote, so it trains the Cyclotron.
 *
 * This is the one documented exception to "deployed Lambdas call AppSync with IAM only" (docs/agent-rules-detail.md): the skill
 * relays the end user's own token and never uses credentials of its own for a read or a write (Ryan, 2026-10-31).
 */
import { currentRelevanceDecisions } from "../../../../lib/relevance-decisions";
import type { AlexaConfig } from "../config";
import { resolveCorpusId } from "../config";

/** Set by the plugin's wiring: the site's AppSync GraphQL endpoint. */
export const GRAPHQL_ENDPOINT_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_GRAPHQL_ENDPOINT";
/** Set by the Cognito wiring: the pool's hosted UI origin, for /oauth2/userInfo (the editor's email for the newsroom's "by" line). */
export const HOSTED_UI_ORIGIN_ENVIRONMENT_VARIABLE = "PAPYRUS_ALEXA_HOSTED_UI_ORIGIN";

/** One unrated Reference as the queue orders it: no text beyond the title until it is read. */
export type ReviewCandidate = {
  id: string;
  lineageId: string;
  title: string;
  sourceUri?: string;
  sourcePublishedAt?: string;
  /** When it reached the newsroom (ties go to the newest). */
  arrivedAt?: string;
  /** The Cyclotron's original P(accept); undefined when it has not decided. */
  probability?: number;
};

/** What the skill says and shows about one Reference, and what a vote needs. */
export type ReviewDetails = {
  title: string;
  deck?: string;
  summary?: string;
  siteName?: string;
  sourceUri?: string;
  sourcePublishedAt?: string;
  decision?: {
    decisionRelationId: string;
    label: string;
    confidence: number | null;
    positiveLabel: string | null;
    reviewRecommended: boolean;
    reviewReason: "program" | "audit" | null;
  };
};

export type VoteInput = {
  referenceId: string;
  action: "accept" | "reject" | "reopen";
  note?: string;
  reasonCode?: string;
  decisionRelationId?: string;
  actorLabel?: string;
};

export type VoteResult = { ok: true; status: string } | { ok: false; refused: boolean; message: string };

/** Everything review needs from the newsroom. The skill gets one per request, bound to the linked editor's token. */
export interface NewsroomReview {
  /** The corpus's unrated References, unordered (the queue orders them). At most `limit`. */
  listUnrated(limit: number): Promise<ReviewCandidate[]>;
  details(candidate: Pick<ReviewCandidate, "id" | "lineageId" | "title" | "sourceUri" | "sourcePublishedAt">): Promise<ReviewDetails>;
  vote(input: VoteInput): Promise<VoteResult>;
  /** The editor's email, for the newsroom's "by" line (an access token carries no email claim). */
  editorEmail(): Promise<string | undefined>;
}

export type FetchLike = (url: string, init: { method: string; headers: Record<string, string>; body?: string }) => Promise<{ ok: boolean; status: number; json(): Promise<unknown>; text(): Promise<string> }>;

export class NewsroomRefusedError extends Error {}

const CANDIDATE_FIELDS = "id lineageId title sourceUri sourcePublishedAt feedArrivalAt createdAt predictedAcceptProbability curationStatus versionState";

const UNRATED_QUERY = `
  query AlexaUnratedReferences($feedStateKey: String!, $limit: Int, $nextToken: String) {
    listReferencesByFeedStateAndPrediction(feedStateKey: $feedStateKey, sortDirection: DESC, limit: $limit, nextToken: $nextToken) {
      items { ${CANDIDATE_FIELDS} }
      nextToken
    }
  }
`;

const ATTACHMENTS_QUERY = `
  query AlexaReferenceAttachments($referenceLineageId: ID!) {
    listReferenceAttachmentsByReferenceLineageAndSortKey(referenceLineageId: $referenceLineageId, limit: 20) {
      items { role sortKey sourceUri metadata }
    }
  }
`;

const DECISIONS_QUERY = `
  query AlexaReferenceDecisions($subjectStateKey: String!) {
    listSemanticRelationsBySubjectState(subjectStateKey: $subjectStateKey, limit: 50, filter: { predicate: { eq: "relevance_decision_is" } }) {
      items { id relationState predicate subjectKind subjectId subjectLineageId objectKind objectId objectLineageId score confidence classifierId modelVersion reviewRecommended createdAt updatedAt metadata }
    }
  }
`;

const METADATA_ATTACHMENT_QUERY = `
  query AlexaReferenceMetadataAttachment($ownerId: ID!) {
    listModelAttachmentsByOwnerRoleAndSortKey(ownerId: $ownerId, limit: 20) {
      items { id ownerKind role status }
    }
  }
`;

const DOWNLOAD_MUTATION = `
  mutation AlexaReferenceMetadataDownload($attachmentId: ID!) {
    createModelAttachmentDownload(attachmentId: $attachmentId) { ok downloadUrl }
  }
`;

const VOTE_MUTATION = `
  mutation AlexaReviewReference($referenceId: ID!, $action: String!, $note: String, $reasonCode: String, $decisionRelationId: ID, $actorLabel: String) {
    reviewReferenceCuration(referenceId: $referenceId, action: $action, note: $note, reasonCode: $reasonCode, decisionRelationId: $decisionRelationId, actorLabel: $actorLabel) {
      ok action referenceId status reasonCode
    }
  }
`;

function record(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      return record(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function probabilityOf(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : undefined;
}

/** The title the newsroom shows: the site name some feeds append (" - Example News", " | Example") is dropped. */
export function displayTitle(title: string, siteName?: string): string {
  if (!siteName) return title.trim();
  const escaped = siteName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return title.replace(new RegExp(`\\s+[-|–—:]\\s+${escaped}\\s*$`, "i"), "").trim() || title.trim();
}

export function createNewsroomReview(options: {
  config: AlexaConfig;
  accessToken: string;
  endpoint: string;
  /** The site's Cognito hosted UI origin, for /oauth2/userInfo. */
  hostedUiOrigin?: string;
  fetch?: FetchLike;
}): NewsroomReview {
  const fetchImpl: FetchLike = options.fetch ?? ((url, init) => fetch(url, init) as never);
  const feedStateKey = `${resolveCorpusId(options.config)}#unrated`;

  async function graphql<T>(query: string, variables: Record<string, unknown>): Promise<T> {
    const response = await fetchImpl(options.endpoint, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: options.accessToken },
      body: JSON.stringify({ query, variables }),
    });
    if (response.status === 401 || response.status === 403) throw new NewsroomRefusedError(`AppSync refused the linked account (${response.status})`);
    const body = record(await response.json());
    const errors = Array.isArray(body.errors) ? body.errors : [];
    if (errors.length > 0) {
      const message = errors.map((error) => text(record(error).message) ?? "error").join("; ");
      if (/unauthori[sz]ed|not authori[sz]ed|access denied/i.test(message)) throw new NewsroomRefusedError(message);
      throw new Error(message);
    }
    return record(body.data) as T;
  }

  return {
    async listUnrated(limit) {
      const candidates: ReviewCandidate[] = [];
      let nextToken: string | undefined;
      do {
        const data = await graphql<{ listReferencesByFeedStateAndPrediction?: { items?: unknown[]; nextToken?: string | null } }>(UNRATED_QUERY, {
          feedStateKey,
          limit: Math.min(100, limit - candidates.length),
          nextToken,
        });
        const page = data.listReferencesByFeedStateAndPrediction;
        for (const raw of page?.items ?? []) {
          const item = record(raw);
          const id = text(item.id);
          const title = text(item.title);
          if (!id || !title) continue;
          if (item.versionState && item.versionState !== "current") continue;
          candidates.push({
            id,
            lineageId: text(item.lineageId) ?? id,
            title,
            ...(text(item.sourceUri) ? { sourceUri: text(item.sourceUri) } : {}),
            ...(text(item.sourcePublishedAt) ? { sourcePublishedAt: text(item.sourcePublishedAt) } : {}),
            ...(text(item.feedArrivalAt) ?? text(item.createdAt) ? { arrivedAt: text(item.feedArrivalAt) ?? text(item.createdAt) } : {}),
            ...(probabilityOf(item.predictedAcceptProbability) === undefined ? {} : { probability: probabilityOf(item.predictedAcceptProbability) }),
          });
        }
        nextToken = page?.nextToken ?? undefined;
      } while (nextToken && candidates.length < limit);
      return candidates;
    },

    async details(candidate) {
      const [attachments, decisions] = await Promise.all([
        graphql<{ listReferenceAttachmentsByReferenceLineageAndSortKey?: { items?: unknown[] } }>(ATTACHMENTS_QUERY, { referenceLineageId: candidate.lineageId }),
        graphql<{ listSemanticRelationsBySubjectState?: { items?: unknown[] } }>(DECISIONS_QUERY, { subjectStateKey: `reference#${candidate.lineageId}#current` }),
      ]);
      const items = (attachments.listReferenceAttachmentsByReferenceLineageAndSortKey?.items ?? []).map(record);
      const preview = record(items.find((item) => item.role === "preview")?.metadata);
      const curation = record(items.find((item) => item.role === "curation")?.metadata);
      const siteName = text(preview.siteName);
      let summary = text(record(curation.summary).text) ?? text(curation.summary);
      if (!summary) summary = await metadataSummary(candidate.id).catch(() => undefined);
      const view = currentRelevanceDecisions((decisions.listSemanticRelationsBySubjectState?.items ?? []) as never).get(candidate.lineageId);
      return {
        title: displayTitle(candidate.title, siteName),
        ...(text(preview.description) ? { deck: text(preview.description) } : {}),
        ...(summary ? { summary } : {}),
        ...(siteName ? { siteName } : {}),
        ...(candidate.sourceUri ? { sourceUri: candidate.sourceUri } : {}),
        ...(candidate.sourcePublishedAt ? { sourcePublishedAt: candidate.sourcePublishedAt } : {}),
        ...(view
          ? {
              decision: {
                decisionRelationId: view.decisionRelationId,
                label: view.label,
                confidence: view.confidence,
                positiveLabel: view.positiveLabel,
                reviewRecommended: view.reviewRecommended,
                reviewReason: view.reviewReason,
              },
            }
          : {}),
      };
    },

    async vote(input) {
      try {
        const data = await graphql<{ reviewReferenceCuration?: { ok?: boolean; status?: string } }>(VOTE_MUTATION, {
          referenceId: input.referenceId,
          action: input.action,
          note: input.note ?? null,
          reasonCode: input.reasonCode ?? null,
          decisionRelationId: input.decisionRelationId ?? null,
          actorLabel: input.actorLabel ?? null,
        });
        const result = data.reviewReferenceCuration;
        if (!result?.ok) return { ok: false, refused: false, message: "the newsroom did not record it" };
        return { ok: true, status: text(result.status) ?? input.action };
      } catch (error) {
        return { ok: false, refused: error instanceof NewsroomRefusedError, message: error instanceof Error ? error.message : String(error) };
      }
    },

    async editorEmail() {
      if (!options.hostedUiOrigin) return undefined;
      try {
        const response = await fetchImpl(`${options.hostedUiOrigin}/oauth2/userInfo`, { method: "GET", headers: { authorization: `Bearer ${options.accessToken}` } });
        return response.ok ? text(record(await response.json()).email) : undefined;
      } catch {
        return undefined;
      }
    },
  };

  /** The summary the reference summarizer wrote (a `metadata` ModelAttachment), fetched through a short-lived signed URL. */
  async function metadataSummary(referenceId: string): Promise<string | undefined> {
    const listed = await graphql<{ listModelAttachmentsByOwnerRoleAndSortKey?: { items?: unknown[] } }>(METADATA_ATTACHMENT_QUERY, { ownerId: referenceId });
    const attachment = (listed.listModelAttachmentsByOwnerRoleAndSortKey?.items ?? []).map(record).find((item) => item.role === "metadata" && item.status !== "deleted");
    const attachmentId = text(attachment?.id);
    if (!attachmentId) return undefined;
    const slot = await graphql<{ createModelAttachmentDownload?: { ok?: boolean; downloadUrl?: string } }>(DOWNLOAD_MUTATION, { attachmentId });
    const url = text(slot.createModelAttachmentDownload?.downloadUrl);
    if (!url) return undefined;
    const response = await fetchImpl(url, { method: "GET", headers: {} });
    if (!response.ok) return undefined;
    const payload = record(await response.json());
    return text(payload.summary) ?? text(record(payload.metadata).summary);
  }
}
