import { Sha256 } from "@aws-crypto/sha256-js";
import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { HttpRequest } from "@smithy/protocol-http";
import { SignatureV4 } from "@smithy/signature-v4";

/**
 * Fail-closed Prospectus authorization for the TypeScript Lambda resolvers (twin of
 * `src/papyrus_content/prospectus_authorize.py`).
 *
 * An account-scoped operation is allowed only when Prospectus says so, for the account the caller named, at the moment of
 * the call. Pool groups alone are never authorization. The site's function role signs the request (SigV4, service
 * `execute-api`) and the caller's own access token travels in `X-Prospectus-Human-Token`.
 *
 * Any doubt denies. Only `reenrollment_required` passes through unchanged, as `ReenrollmentRequired`, so the CLI and
 * console can tell the person to sign in again. The AppSync JavaScript resolvers do the same job in
 * `amplify/data/resolvers/prospectus-authorize.js`.
 */

export const PROSPECTUS_ACCOUNT_HEADER = "x-prospectus-account";
export const PROSPECTUS_HUMAN_TOKEN_HEADER = "x-prospectus-human-token";
export const PROSPECTUS_ENABLE_ENVIRONMENT_VARIABLE = "PAPYRUS_PROSPECTUS_AUTHORIZE";
export const PROSPECTUS_ENDPOINT_ENVIRONMENT_VARIABLE = "PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT";
const REQUEST_TIMEOUT_MILLISECONDS = 5000;

export type ProspectusOperation = "console:read" | "console:write" | "members:read";

const READ_FIELD_PREFIXES = ["list", "get", "search", "count", "describe"];
const MEMBERS_READ_FIELDS = new Set(["listAccountMembers", "getAccountMembers"]);
const ACCOUNT_IDENTIFIER_PATTERN = /^[A-Za-z0-9-]{1,64}$/;

export class AccountRequired extends Error {
  constructor(message = "account_required") {
    super(message);
    this.name = "AccountRequired";
  }
}

export class ReenrollmentRequired extends Error {
  constructor(message = "reenrollment_required") {
    super(message);
    this.name = "ReenrollmentRequired";
  }
}

export class AuthorizationDenied extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthorizationDenied";
  }
}

export interface Decision {
  allowed: boolean;
  accountId: string;
  operation: ProspectusOperation;
  reason?: string;
  role?: string;
}

export type ProspectusTransport = (url: string, headers: Record<string, string>, body: string) => Promise<{ status: number; body: unknown }>;

export function operationFor(fieldName: string): ProspectusOperation {
  if (MEMBERS_READ_FIELDS.has(fieldName)) return "members:read";
  return READ_FIELD_PREFIXES.some((prefix) => fieldName.startsWith(prefix)) ? "console:read" : "console:write";
}

export function authorizationEnabled(environment: Record<string, string | undefined> = process.env): boolean {
  return ["1", "true", "yes", "on"].includes((environment[PROSPECTUS_ENABLE_ENVIRONMENT_VARIABLE] ?? "").trim().toLowerCase());
}

function regionFor(host: string, environment: Record<string, string | undefined>): string {
  const match = /\.execute-api\.([a-z0-9-]+)\.amazonaws\.com$/.exec(host);
  return match?.[1] ?? environment.AWS_REGION ?? environment.AWS_DEFAULT_REGION ?? "us-east-1";
}

export function signedTransport(environment: Record<string, string | undefined> = process.env): ProspectusTransport {
  return async (urlText, headers, body) => {
    const url = new URL(urlText);
    const signer = new SignatureV4({
      service: "execute-api",
      region: regionFor(url.host, environment),
      credentials: defaultProvider(),
      sha256: Sha256,
    });
    const signed = await signer.sign(
      new HttpRequest({ protocol: url.protocol, hostname: url.hostname, path: url.pathname, method: "POST", headers: { ...headers, host: url.host }, body }),
    );
    const response = await fetch(url, {
      method: "POST",
      headers: signed.headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MILLISECONDS),
    });
    return { status: response.status, body: await response.json().catch(() => ({})) };
  };
}

function denied(accountId: string, operation: ProspectusOperation, reason: string): Decision {
  return { allowed: false, accountId, operation, reason };
}

/**
 * Ask Prospectus whether the token's person may perform `operation` on `accountId` right now. Call it immediately
 * before each effect: the answer is point-in-time. Throws `ReenrollmentRequired` on a `401` or `403`
 * `reenrollment_required`; every other failure is a denied decision.
 */
export async function authorize(
  accountId: string,
  operation: ProspectusOperation,
  humanToken: string | undefined | null,
  options: { endpoint?: string; transport?: ProspectusTransport; environment?: Record<string, string | undefined> } = {},
): Promise<Decision> {
  const environment = options.environment ?? process.env;
  if (typeof accountId !== "string" || !ACCOUNT_IDENTIFIER_PATTERN.test(accountId)) return denied(String(accountId), operation, "account_invalid");
  if (!humanToken) return denied(accountId, operation, "human_token_required");
  const base = (options.endpoint ?? environment[PROSPECTUS_ENDPOINT_ENVIRONMENT_VARIABLE] ?? "").trim();
  if (!base.startsWith("https://")) return denied(accountId, operation, "prospectus_unavailable");
  const url = `${base.replace(/\/+$/, "")}/v1/accounts/${accountId}/authorize`;
  const headers = { "content-type": "application/json", [PROSPECTUS_HUMAN_TOKEN_HEADER]: humanToken };
  let status: number;
  let answer: Record<string, unknown>;
  try {
    const response = await (options.transport ?? signedTransport(environment))(url, headers, JSON.stringify({ operation }));
    status = response.status;
    answer = typeof response.body === "object" && response.body !== null ? (response.body as Record<string, unknown>) : {};
  } catch {
    return denied(accountId, operation, "prospectus_unavailable");
  }
  if ((status === 401 || status === 403) && answer.error === "reenrollment_required") throw new ReenrollmentRequired();
  if (status === 200) {
    if (answer.allowed !== true) return denied(accountId, operation, "not_allowed");
    if (answer.accountId !== accountId) return denied(accountId, operation, "account_mismatch");
    return { allowed: true, accountId, operation, role: typeof answer.role === "string" ? answer.role : undefined };
  }
  if (status === 403) return denied(accountId, operation, "forbidden");
  if (status === 401) return denied(accountId, operation, "unauthenticated");
  return denied(accountId, operation, "prospectus_unavailable");
}

type Identity = Record<string, unknown> | null | undefined;

/**
 * True for an IAM principal of the function's own account: the backend's own machine calls, not a signed-in person.
 * A Cognito identity-pool user carries a Cognito identity, and a user-pool caller carries a subject or claims.
 */
export function isSiteFunctionCaller(identity: Identity): boolean {
  if (!identity || typeof identity !== "object") return false;
  const account = identity.accountId;
  const parts = typeof identity.userArn === "string" ? identity.userArn.split(":") : [];
  if (!account || parts.length < 6 || parts[0] !== "arn" || parts[4] !== account) return false;
  return !["cognitoIdentityId", "cognitoIdentityPoolId", "cognitoIdentityAuthType", "sub", "claims"].some((key) => Boolean(identity[key]));
}

export interface AuthorizableEvent {
  identity?: Identity;
  request?: { headers?: Record<string, string | undefined> | null } | null;
}

/**
 * Gate one Lambda resolver call. Returns `null` when the flag is off or the caller is a site function; throws
 * `AccountRequired`, `ReenrollmentRequired` or `AuthorizationDenied`; returns the allowed decision otherwise.
 */
export async function requireAuthorized(
  appSyncEvent: object,
  fieldName: string,
  options: { environment?: Record<string, string | undefined>; endpoint?: string; transport?: ProspectusTransport } = {},
): Promise<Decision | null> {
  const environment = options.environment ?? process.env;
  if (!authorizationEnabled(environment)) return null;
  const event = appSyncEvent as AuthorizableEvent;
  if (isSiteFunctionCaller(event.identity)) return null;
  const headers = Object.fromEntries(Object.entries(event.request?.headers ?? {}).map(([key, value]) => [key.toLowerCase(), value ?? ""]));
  const accountId = (headers[PROSPECTUS_ACCOUNT_HEADER] ?? "").trim();
  if (!accountId) throw new AccountRequired();
  const decision = await authorize(accountId, operationFor(fieldName), headers[PROSPECTUS_HUMAN_TOKEN_HEADER], { ...options, environment });
  if (!decision.allowed) throw new AuthorizationDenied(decision.reason ?? "not_allowed");
  return decision;
}
