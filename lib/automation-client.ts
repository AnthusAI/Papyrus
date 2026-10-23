"use client";

import { generateClient } from "aws-amplify/data";
import type { AutomationResult, RunNowResult } from "./automation-overview";

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

type RunGraphQLResult = { data?: { runAutomation?: unknown }; errors?: { message?: string; errorType?: string }[] };

/**
 * Starts a run of the automation's procedure now, as the signed-in editor or admin. The function behind the
 * mutation checks the groups again, refuses a disabled automation or one at its limit, and writes the row that
 * links the run to the automation's history. `input` is sent as JSON text; null uses the record's own input.
 */
export async function runAutomationNow(automationId: string, input: Record<string, unknown> | null): Promise<RunNowResult> {
  const client = generateClient({ authMode: "userPool" });
  let result: RunGraphQLResult;
  try {
    result = (await client.graphql({
      query: `mutation RunAutomation($automationId: String!, $input: AWSJSON) { runAutomation(automationId: $automationId, input: $input) }`,
      variables: { automationId, input: input === null ? null : JSON.stringify(input) },
    })) as RunGraphQLResult;
  } catch (error) {
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as RunGraphQLResult;
  }
  const refused = result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`));
  if (refused) return { error: "forbidden" };
  if (result.errors?.length || result.data?.runAutomation === undefined || result.data.runAutomation === null) return { state: "unavailable" };
  const raw = result.data.runAutomation;
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as RunNowResult;
}
