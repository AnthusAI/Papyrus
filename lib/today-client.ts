"use client";

import { generateClient } from "aws-amplify/data";
import type { TodayResult } from "./today-overview";

type GraphQLResult = { data?: { todayOverview?: unknown }; errors?: { message?: string; errorType?: string }[] };

/** The viewer's own time zone, so "today" is the viewer's day. Null when the browser does not say. */
export function viewerTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** Reads Today through the site's own authenticated API (user pool, editor or admin). The function behind the query reads by index. */
export async function loadTodayOverview(timeZone: string | null = viewerTimeZone()): Promise<TodayResult> {
  const client = generateClient({ authMode: "userPool" });
  let result: GraphQLResult;
  try {
    result = (await client.graphql({
      query: `query TodayOverview($day: String, $timeZone: String) { todayOverview(day: $day, timeZone: $timeZone) }`,
      variables: { day: null, timeZone },
    })) as GraphQLResult;
  } catch (error) {
    result = (error && typeof error === "object" && "errors" in error ? error : { errors: [{ message: "failed" }] }) as GraphQLResult;
  }
  const refused = result.errors?.some((entry) => /unauthorized|not authorized|forbidden/i.test(`${entry.errorType ?? ""} ${entry.message ?? ""}`));
  if (refused) return { error: "forbidden" };
  if (result.errors?.length || result.data?.todayOverview === undefined || result.data.todayOverview === null) return { state: "unavailable" };
  const raw = result.data.todayOverview;
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as TodayResult;
}
