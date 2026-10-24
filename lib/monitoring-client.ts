"use client";

import { generateClient } from "aws-amplify/data";
import type { MonitoringEmailDetails, MonitoringResult } from "./monitoring-overview";

type QueryField = "monitoringOverview" | "monitoringEmailSubmission";
type GraphQLResult = { data?: Partial<Record<QueryField, unknown>>; errors?: { message?: string; errorType?: string }[] };

async function query<T>(field: QueryField, queryText: string, variables: Record<string, string>): Promise<T | { error: "forbidden" } | { state: "unavailable" }> {
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
