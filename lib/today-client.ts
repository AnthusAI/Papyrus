"use client";

import { generateClient } from "aws-amplify/data";
import { overdueWakeRefusedText, overdueWakeSentText, type AcknowledgeResult, type OverdueWakeOutcome, type OverdueWakeResult, type TodayResult } from "./today-overview";

type GraphQLResult<Field extends string> = { data?: Partial<Record<Field, unknown>>; errors?: { message?: string; errorType?: string }[] };

async function call<Field extends string>(query: string, variables: Record<string, unknown>): Promise<GraphQLResult<Field>> {
  const client = generateClient({ authMode: "userPool" });
  try {
    return (await client.graphql({ query, variables })) as GraphQLResult<Field>;
  } catch (error) {
    return (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult<Field>;
  }
}

function refused(result: GraphQLResult<string>): boolean {
  return Boolean(result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`)));
}

function parsed<T>(raw: unknown): T {
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as T;
}

/** Reads Today through the site's own authenticated API (user pool, editor or admin). The function behind the query reads by index. No time zone is
 *  sent: the day and its times are the site's own (its publication.timeZone), whatever zone the viewer's device is in. */
export async function loadTodayOverview(): Promise<TodayResult> {
  const result = await call<"todayOverview">(`query TodayOverview($day: String, $timeZone: String) { todayOverview(day: $day, timeZone: $timeZone) }`, { day: null, timeZone: null });
  if (refused(result)) return { error: "forbidden" };
  const raw = result.data?.todayOverview;
  if (result.errors?.length || raw === undefined || raw === null) return { state: "unavailable" };
  return parsed<TodayResult>(raw);
}

/** Acknowledges a failed run, or settles a run whose outcome is unknown: the run leaves Today's attention list and records who did it. */
export async function acknowledgeTodayRun(runId: string): Promise<AcknowledgeResult> {
  const result = await call<"acknowledgeRun">(`mutation AcknowledgeRun($runId: String!) { acknowledgeRun(runId: $runId) }`, { runId });
  if (refused(result)) return { error: "forbidden" };
  const raw = result.data?.acknowledgeRun;
  if (result.errors?.length || raw === undefined || raw === null) return { state: "unavailable" };
  return parsed<AcknowledgeResult>(raw);
}

const AGENT_WAKE = "mutation AgentWake($input: AWSJSON!) { agentWake(input: $input) }";

/** Wake now on an Overdue Delivery or soft review deadline: the record's own timer wake goes on the site's queue again, with the same key (`agents_wake_overdue`,
 *  through the Automation page's function, which admits editors and admins). Who asks comes from the signed-in session. */
export async function wakeOverdueRecord(record: string, id: string, reason: string): Promise<OverdueWakeOutcome> {
  const result = await call<"agentWake">(AGENT_WAKE, { input: JSON.stringify({ op: "agents_wake_overdue", record, id, reason: reason.trim() }) });
  if (refused(result)) return { state: "refused", words: overdueWakeRefusedText("forbidden") };
  const raw = result.data?.agentWake;
  if (result.errors?.length || raw === undefined || raw === null) return { state: "refused", words: overdueWakeRefusedText("unavailable") };
  const answer = parsed<{ ok?: boolean; result?: OverdueWakeResult; error?: string; message?: string }>(raw);
  if (!answer || answer.ok !== true || !answer.result) return { state: "refused", words: overdueWakeRefusedText(String(answer?.error ?? "unavailable"), answer?.message) };
  return { state: "sent", words: overdueWakeSentText(answer.result) };
}
