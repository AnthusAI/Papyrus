"use client";

import { generateClient } from "aws-amplify/data";
import type { MonitoringResult } from "./monitoring-overview";

type GraphQLResult = { data?: { monitoringOverview?: unknown }; errors?: { message?: string; errorType?: string }[] };

/**
 * Reads the monitoring overview through the site's own authenticated API (user pool, editor or admin).
 * The browser holds no table name, key or secret: the function behind the query does the read.
 */
export async function loadMonitoringOverview(scope: "publication" | "all"): Promise<MonitoringResult> {
  const client = generateClient({ authMode: "userPool" });
  let result: GraphQLResult;
  try {
    result = (await client.graphql({
      query: `query MonitoringOverview($scope: String) { monitoringOverview(scope: $scope) }`,
      variables: { scope },
    })) as GraphQLResult;
  } catch (error) {
    // Amplify throws the response when AppSync returns errors.
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
  const refused = result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`));
  if (refused) return { error: "forbidden" };
  if (result.errors?.length || result.data?.monitoringOverview === undefined || result.data.monitoringOverview === null) return { state: "unavailable" };
  const raw = result.data.monitoringOverview;
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as MonitoringResult;
}
