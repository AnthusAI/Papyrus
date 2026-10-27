import { createHmac } from "node:crypto";
import type { ProspectusSignedInSession } from "./prospectus-session";
import { hasEditorRights, STAFF_GROUPS } from "./staff-groups";

export const SITE_SUBJECT_PATTERN = /^ss1_[A-Za-z0-9_-]{43}$/;
export const INTERIM_SUBJECT_PATTERN = /^ssdev_[A-Za-z0-9_-]{43}$/;
export const READER_DEV_SECRET_ENV = "PAPYRUS_READER_DEV_SECRET";
export const READER_STAFF_GROUPS = STAFF_GROUPS;

const MINIMUM_DEV_SECRET_LENGTH = 16;
const INTERIM_SUBJECT_PREFIX = "ssdev_";
const INTERIM_ENVIRONMENTS = ["development", "test"];

type EnvironmentVariables = Record<string, string | undefined>;

export function interimSubjectsAllowed(environment: EnvironmentVariables = process.env): boolean {
  if (environment.NODE_ENV === "production") return false;
  const siteEnvironment = (environment.SITE_ENV ?? "").trim();
  if (!INTERIM_ENVIRONMENTS.includes(siteEnvironment)) return false;
  return (environment[READER_DEV_SECRET_ENV] ?? "").length >= MINIMUM_DEV_SECRET_LENGTH;
}

export function interimSubject(personId: string, devSecret: string): string {
  return INTERIM_SUBJECT_PREFIX + createHmac("sha256", devSecret).update(personId).digest("base64url");
}

/**
 * The reader's per-site pairwise id, or null. Production reads only the siteSubject Prospectus returned;
 * the interim `ssdev_` value exists in development and test only (lib/reader-subject.md).
 */
export function readerSubject(
  session: Pick<ProspectusSignedInSession, "personId" | "siteSubject"> | null | undefined,
  environment: EnvironmentVariables = process.env,
): string | null {
  if (!session) return null;
  if (typeof session.siteSubject === "string" && SITE_SUBJECT_PATTERN.test(session.siteSubject)) return session.siteSubject;
  if (!interimSubjectsAllowed(environment) || !session.personId) return null;
  return interimSubject(session.personId, environment[READER_DEV_SECRET_ENV] as string);
}

/** Staff membership from the Cognito groups claim of the access token that the sealed session cookie carries. */
export function readerIsStaff(session: Pick<ProspectusSignedInSession, "accessToken"> | null | undefined): boolean {
  const token = session?.accessToken;
  if (typeof token !== "string") return false;
  const payload = token.split(".")[1];
  if (!payload) return false;
  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { "cognito:groups"?: unknown };
    const groups = claims["cognito:groups"];
    return Array.isArray(groups) && hasEditorRights(groups);
  } catch {
    return false;
  }
}
