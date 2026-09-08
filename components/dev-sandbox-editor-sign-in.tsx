"use client";

import { fetchAuthSession, signIn } from "aws-amplify/auth";
import { configureAmplifyClient } from "./amplify-client-provider";
import type { DevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";

export async function ensureDevSandboxEditorSession(
  credentials: DevSandboxEditorAuth | null | undefined,
): Promise<void> {
  if (!credentials) return;

  configureAmplifyClient();

  const existing = await fetchAuthSession();
  if (existing.tokens?.accessToken) return;

  const result = await signIn({
    username: credentials.username,
    password: credentials.password,
  });
  if (!result.isSignedIn) return;

  await fetchAuthSession({ forceRefresh: true });
}
