import type { NextRequest, NextResponse } from "next/server";
import { fetchAuthSession } from "aws-amplify/auth/server";
import { getAmplifyServerRuntime } from "./amplify-server-runtime";

export type StagingAccess = "anonymous" | "forbidden" | "ok";

const STAGING_ALLOWED_GROUPS = ["editor", "admin"];

export function groupsFromIdTokenPayload(payload: Record<string, unknown> | undefined): string[] {
  const raw = payload?.["cognito:groups"];
  if (Array.isArray(raw)) return raw.filter((group): group is string => typeof group === "string");
  if (typeof raw === "string" && raw) return [raw];
  return [];
}

export function accessForGroups(groups: string[] | null): StagingAccess {
  if (groups === null) return "anonymous";
  return groups.some((group) => STAGING_ALLOWED_GROUPS.includes(group)) ? "ok" : "forbidden";
}

export async function getStagingAccess(request: NextRequest, response: NextResponse): Promise<StagingAccess> {
  const { runWithAmplifyServerContext } = getAmplifyServerRuntime();
  const groups = await runWithAmplifyServerContext({
    nextServerContext: { request, response },
    operation: async (contextSpec) => {
      try {
        const session = await fetchAuthSession(contextSpec);
        const idTokenPayload = session.tokens?.idToken?.payload as Record<string, unknown> | undefined;
        if (!session.tokens?.idToken) return null;
        return groupsFromIdTokenPayload(idTokenPayload);
      } catch {
        return null;
      }
    },
  });
  return accessForGroups(groups);
}
