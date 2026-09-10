"use client";

import { fetchAuthSession, signIn, signOut } from "aws-amplify/auth";
import { configureAmplifyClient } from "./amplify-client-provider";
import type { DevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";

const EDITOR_GROUPS = new Set(["editor", "admin"]);

function readSessionGroups(session: Awaited<ReturnType<typeof fetchAuthSession>>): string[] {
  const accessPayload = session.tokens?.accessToken?.payload ?? {};
  const idPayload = session.tokens?.idToken?.payload ?? {};
  const rawGroups = [
    accessPayload["cognito:groups"],
    accessPayload.groups,
    idPayload["cognito:groups"],
    idPayload.groups,
  ];
  const groups: string[] = [];
  for (const value of rawGroups) {
    if (typeof value === "string" && value.trim()) groups.push(value.trim());
    else if (Array.isArray(value)) {
      for (const entry of value) {
        if (typeof entry === "string" && entry.trim()) groups.push(entry.trim());
      }
    }
  }
  return [...new Set(groups)];
}

function sessionHasEditorAccess(session: Awaited<ReturnType<typeof fetchAuthSession>>): boolean {
  if (!session.tokens?.accessToken) return false;
  return readSessionGroups(session).some((group) => EDITOR_GROUPS.has(group));
}

export async function ensureDevSandboxEditorSession(
  credentials: DevSandboxEditorAuth | null | undefined,
): Promise<void> {
  if (!credentials) return;

  configureAmplifyClient();

  const existing = await fetchAuthSession();
  if (sessionHasEditorAccess(existing)) return;

  if (existing.tokens?.accessToken) {
    try {
      await signOut();
    } catch {
      // Continue into seed sign-in even if sign-out fails.
    }
  }

  const result = await signIn({
    username: credentials.username,
    password: credentials.password,
  });
  if (!result.isSignedIn) return;

  await fetchAuthSession({ forceRefresh: true });
}
