"use client";

import { generateClient } from "aws-amplify/data";
import type { AutomationResult } from "./automation-overview";

type GraphQLResult = { data?: { automationOverview?: unknown }; errors?: { message?: string; errorType?: string }[] };

/**
 * Reads the automations through the site's own authenticated API (user pool, editor or admin).
 * The browser holds no table name, key or secret: the function behind the query does the reads.
 */
export async function loadAutomationOverview(): Promise<AutomationResult> {
  const client = generateClient({ authMode: "userPool" });
  let result: GraphQLResult;
  try {
    result = (await client.graphql({
      query: `query AutomationOverview($automationId: String) { automationOverview(automationId: $automationId) }`,
      variables: {},
    })) as GraphQLResult;
  } catch (error) {
    // Amplify throws the response when AppSync returns errors.
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
  const refused = result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`));
  if (refused) return { error: "forbidden" };
  if (result.errors?.length || result.data?.automationOverview === undefined || result.data.automationOverview === null) return { state: "unavailable" };
  const raw = result.data.automationOverview;
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as AutomationResult;
}
