"use client";

import { fetchAuthSession } from "aws-amplify/auth";
import { configureAmplifyClient } from "./amplify-client-provider";

export type ReaderAuthSnapshot =
  | { status: "loading"; label: string; email?: null }
  | { status: "signedOut"; label: string; email?: null }
  | { status: "signedIn"; label: string; email?: string | null };

export type ReaderSessionSnapshot = {
  auth: ReaderAuthSnapshot;
  groups: string[];
  hasSession: boolean;
};

export async function loadReaderSessionSnapshot(options?: { forceRefresh?: boolean }): Promise<ReaderSessionSnapshot> {
  configureAmplifyClient();
  try {
    const session = await fetchAuthSession({ forceRefresh: options?.forceRefresh === true });
    const accessPayload = session.tokens?.accessToken?.payload ?? {};
    const idPayload = session.tokens?.idToken?.payload ?? {};
    const email = readTextClaim(idPayload.email ?? accessPayload.email);
    const groups = dedupeGroups([
      ...readGroups(accessPayload["cognito:groups"]),
      ...readGroups(accessPayload.groups),
      ...readGroups(idPayload["cognito:groups"]),
      ...readGroups(idPayload.groups),
    ]);
    const label = readIdentityLabel({
      email,
      name: idPayload.name ?? accessPayload.name,
      username: idPayload["cognito:username"] ?? accessPayload["cognito:username"] ?? accessPayload.username,
      sub: idPayload.sub ?? accessPayload.sub,
    });

    if (!session.tokens?.accessToken) {
      return {
        auth: { status: "signedOut", label: "Signed out" },
        groups,
        hasSession: false,
      };
    }

    return {
      auth: { status: "signedIn", label, email },
      groups,
      hasSession: true,
    };
  } catch (error) {
    if (isUnauthenticatedError(error)) {
      return {
        auth: { status: "signedOut", label: "Signed out" },
        groups: [],
        hasSession: false,
      };
    }
    throw error;
  }
}

export function isUnauthenticatedError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /unauth|not.?authorized|not authenticated|no current user|not signed in|session expired|token expired|invalid.*token|\b401\b/i.test(message);
}

function readIdentityLabel(claims: {
  email: unknown;
  name: unknown;
  username: unknown;
  sub: unknown;
}): string {
  return readTextClaim(claims.email)
    ?? readTextClaim(claims.name)
    ?? readTextClaim(claims.username)
    ?? readTextClaim(claims.sub)
    ?? "Signed in";
}

function readTextClaim(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readGroups(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((entry) => normalizeGroupName(String(entry))).filter(Boolean) as string[];
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return [];
    if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed)) {
          return parsed
            .map((entry) => normalizeGroupName(String(entry)))
            .filter(Boolean) as string[];
        }
      } catch {
      }
    }
    return trimmed
      .split(/[,\s]+/)
      .map((entry) => normalizeGroupName(entry))
      .filter(Boolean) as string[];
  }
  return [];
}

function dedupeGroups(groups: string[]): string[] {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const group of groups) {
    const normalized = normalizeGroupName(group);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    values.push(normalized);
  }
  return values;
}

function normalizeGroupName(value: string): string {
  return value.trim().replace(/^["'[\](){}]+|["'[\](){}]+$/g, "").toLowerCase();
}
