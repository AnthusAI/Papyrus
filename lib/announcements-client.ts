"use client";

import { generateClient } from "aws-amplify/data";
import { ANNOUNCEMENT_MUTATION_OPERATIONS, ANNOUNCEMENT_QUERY_OPERATIONS } from "../amplify/functions/announcements/operations";
import type { AnnouncementFailure } from "./announcements-model";

export type AnnouncementOperation = (typeof ANNOUNCEMENT_QUERY_OPERATIONS)[number] | (typeof ANNOUNCEMENT_MUTATION_OPERATIONS)[number];
export type AnnouncementsApi = <T extends object = Record<string, unknown>>(operation: AnnouncementOperation, input?: Record<string, unknown>) => Promise<({ ok: true } & T) | AnnouncementFailure>;

type GraphQLResult = { data?: Record<string, unknown>; errors?: { message?: string; errorType?: string }[] };

export function announcementOperationDocument(operation: AnnouncementOperation): string {
  const kind = (ANNOUNCEMENT_MUTATION_OPERATIONS as readonly string[]).includes(operation) ? "mutation" : "query";
  const title = operation.charAt(0).toUpperCase() + operation.slice(1);
  return `${kind} ${title}($input: AWSJSON) { ${operation}(input: $input) }`;
}

/** Calls one operation through the site's authenticated API. The browser holds no table name, key or secret; the function checks the role again. */
export const callAnnouncements: AnnouncementsApi = async (operation, input = {}) => {
  const client = generateClient({ authMode: "userPool" });
  let result: GraphQLResult;
  try {
    result = (await client.graphql({ query: announcementOperationDocument(operation), variables: { input: JSON.stringify(input) } })) as GraphQLResult;
  } catch (error) {
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
  if (result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`))) {
    return { ok: false, error: "forbidden" };
  }
  const raw = result.data?.[operation];
  if (result.errors?.length || raw === undefined || raw === null) return { ok: false, error: "unavailable", message: "The announcements service did not answer. It may not be deployed on this site yet." };
  const parsed = (typeof raw === "string" ? JSON.parse(raw) : raw) as { ok?: boolean };
  if (parsed && typeof parsed === "object" && "ok" in parsed) return parsed as never;
  return { ok: false, error: "unavailable", message: "The announcements service gave an answer this page does not understand." };
};
