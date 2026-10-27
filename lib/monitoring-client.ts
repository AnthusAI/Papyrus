"use client";

import { generateClient } from "aws-amplify/data";
import { emailReferenceBatches } from "./monitoring-overview";
import type {
  EmailDecisionResult,
  EmailReferenceImportItem,
  EmailReferenceImportOutcome,
  MonitoringEmailArticleResolution,
  MonitoringEmailDetails,
  MonitoringResult,
} from "./monitoring-overview";

type QueryField = "monitoringOverview" | "monitoringEmailSubmission" | "monitoringDecideEmailSubmission" | "monitoringResolveEmailArticleLink" | "intakeEmailSubmissionReferences" | "monitoringQueueEmailReference";
type GraphQLResult = { data?: Partial<Record<QueryField, unknown>>; errors?: { message?: string; errorType?: string }[] };

async function query<T>(field: QueryField, queryText: string, variables: Record<string, string | number>): Promise<T | { error: "forbidden" } | { state: "unavailable" }> {
  const client = generateClient({ authMode: "userPool" });
  let result: GraphQLResult;
  try {
    result = (await client.graphql({ query: queryText, variables })) as GraphQLResult;
  } catch (error) {
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
  const refused = result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`));
  if (refused) return { error: "forbidden" };
  const raw = result.data?.[field];
  if (result.errors?.length || raw === undefined || raw === null) return { state: "unavailable" };
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as T;
}

/** Reads monitoring data only through the site's authenticated editor/admin API. */
export async function loadMonitoringOverview(scope: "publication" | "all"): Promise<MonitoringResult> {
  return query<MonitoringResult>("monitoringOverview",
    `query MonitoringOverview($scope: String) { monitoringOverview(scope: $scope) }`, { scope });
}

/** Loads one receipt's safe plain-text rendering and its already extracted candidate links. */
export async function loadMonitoringEmailSubmission(receiptId: string): Promise<MonitoringEmailDetails> {
  return query<MonitoringEmailDetails>("monitoringEmailSubmission",
    `query MonitoringEmailSubmission($receiptId: String!) { monitoringEmailSubmission(receiptId: $receiptId) }`, { receiptId });
}

/**
 * Accept or Reject one held email submission. "Accept" releases it into the normal intake and
 * "Reject" discards it; the editor and the optional reason are recorded server-side.
 */
export async function decideMonitoringEmailSubmission(
  receiptId: string, decision: "accept" | "reject", reason: string,
): Promise<EmailDecisionResult> {
  return query<EmailDecisionResult>("monitoringDecideEmailSubmission",
    `mutation MonitoringDecideEmailSubmission($receiptId: String!, $decision: String!, $reason: String) { monitoringDecideEmailSubmission(receiptId: $receiptId, decision: $decision, reason: $reason) }`,
    { receiptId, decision: decision === "accept" ? "release" : "discard", reason });
}

/** Resolve one explicitly selected Beehiiv article redirect; this may register a click with the sender. */
export async function resolveMonitoringEmailArticleLink(receiptId: string, candidateIndex: number): Promise<MonitoringEmailArticleResolution> {
  return query<MonitoringEmailArticleResolution>("monitoringResolveEmailArticleLink",
    `mutation MonitoringResolveEmailArticleLink($receiptId: String!, $candidateIndex: Int!) { monitoringResolveEmailArticleLink(receiptId: $receiptId, candidateIndex: $candidateIndex) }`,
    { receiptId, candidateIndex });
}

/** Use the existing editor-authorized Reference intake; 20 is its request batch size, not a total limit. */
export async function importMonitoringEmailCandidates(
  receiptId: string,
  items: EmailReferenceImportItem[],
): Promise<EmailReferenceImportOutcome> {
  const client = generateClient({ authMode: "userPool" });
  const references: EmailReferenceImportOutcome["references"] = [];
  for (const batch of emailReferenceBatches(items)) {
    let result: GraphQLResult;
    try {
      result = (await client.graphql({
        query: `mutation IntakeEmailSubmissionReferences($input: AWSJSON!) { intakeEmailSubmissionReferences(input: $input) }`,
        variables: { input: JSON.stringify({ receiptId, items: batch }) },
      })) as GraphQLResult;
    } catch {
      return { imported: references.length, references, error: "The import stopped. Completed links are safe to retry." };
    }
    if (result.errors?.length) {
      return { imported: references.length, references, error: "The import stopped. Completed links are safe to retry." };
    }
    const raw = result.data?.intakeEmailSubmissionReferences;
    let response: { ok?: boolean; references?: EmailReferenceImportOutcome["references"] } | null | undefined;
    try {
      response = (typeof raw === "string" ? JSON.parse(raw) : raw) as typeof response;
    } catch {
      return { imported: references.length, references, error: "The import response could not be read. Completed links are safe to retry." };
    }
    if (!response?.ok || !Array.isArray(response.references) || response.references.length !== batch.length) {
      return { imported: references.length, references, error: "The import was not accepted. Check your editor access and retry." };
    }
    references.push(...response.references);
    for (const [index, reference] of response.references.entries()) {
      const queued = await query<{ queued: boolean }>("monitoringQueueEmailReference",
        `mutation MonitoringQueueEmailReference($input: AWSJSON!) { monitoringQueueEmailReference(input: $input) }`,
        { input: JSON.stringify({ receiptId, ...batch[index], referenceId: reference.id }) });
      if (!("queued" in queued) || !queued.queued) {
        return { imported: references.length, references,
          error: "References were registered, but predictions could not be queued. Retry these selected links safely." };
      }
    }
  }
  return { imported: references.length, references };
}
