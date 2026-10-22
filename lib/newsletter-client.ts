"use client";

import { generateClient } from "aws-amplify/data";
import type { NewsletterFailure } from "./newsletter-model";

/** The operations the newsroom Newsletter panel calls. All take and return AWSJSON; the function behind them checks the role again. */
export const NEWSLETTER_QUERY_OPERATIONS = [
  "newsletterOverview", "newsletterIssues", "newsletterIssue", "newsletterPreview", "newsletterIssueDeliveries", "newsletterSubscribers", "newsletterExport",
] as const;
export const NEWSLETTER_MUTATION_OPERATIONS = [
  "newsletterApproveIssue", "newsletterCancelIssue", "newsletterStopIssue", "newsletterTestSend", "newsletterCreateDraft", "newsletterErase", "newsletterResume",
] as const;
export type NewsletterOperation = (typeof NEWSLETTER_QUERY_OPERATIONS)[number] | (typeof NEWSLETTER_MUTATION_OPERATIONS)[number];

type GraphQLResult = { data?: Record<string, unknown>; errors?: { message?: string; errorType?: string }[] };

export type NewsletterApi = <T extends object = Record<string, unknown>>(operation: NewsletterOperation, input?: Record<string, unknown>) => Promise<({ ok: true } & T) | NewsletterFailure>;

export function newsletterOperationDocument(operation: NewsletterOperation): string {
  const kind = (NEWSLETTER_MUTATION_OPERATIONS as readonly string[]).includes(operation) ? "mutation" : "query";
  const title = operation.charAt(0).toUpperCase() + operation.slice(1);
  return `${kind} ${title}($input: AWSJSON) { ${operation}(input: $input) }`;
}

/** Calls one operation through the site's authenticated API (user pool). The browser holds no table name, key or address list. */
export const callNewsletter: NewsletterApi = async (operation, input = {}) => {
  const client = generateClient({ authMode: "userPool" });
  let result: GraphQLResult;
  try {
    result = (await client.graphql({ query: newsletterOperationDocument(operation), variables: { input: JSON.stringify(input) } })) as GraphQLResult;
  } catch (error) {
    // Amplify throws the response when AppSync returns errors.
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
  if (result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) {
    return { ok: false, error: "forbidden" };
  }
  const raw = result.data?.[operation];
  if (result.errors?.length || raw === undefined || raw === null) return { ok: false, error: "unavailable" };
  try {
    const parsed = (typeof raw === "string" ? JSON.parse(raw) : raw) as { ok?: boolean };
    return parsed && typeof parsed === "object" && "ok" in parsed ? (parsed as never) : { ok: false, error: "unavailable" };
  } catch {
    return { ok: false, error: "unavailable" };
  }
};
