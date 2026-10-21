import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";
import { GetParameterCommand, SSMClient } from "@aws-sdk/client-ssm";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import {
  ProspectusSiteAccounts,
  signedProspectusTransport,
  type GoogleOnlyCognitoClient,
  type PendingProspectusSignIn,
  type ProspectusTransport,
} from "./prospectus-site-identity";

/**
 * Browser state for signing in through Prospectus, kept in two sealed cookies so
 * the site holds no session table. The pending cookie carries one sign-in
 * attempt (challenge, state, PKCE verifier) from the redirect to the callback;
 * the session cookie carries the signed-in person and their Cognito access token
 * until that token expires. Both are AES-256-GCM sealed with a per-cookie key
 * derived from the site's generated sealing secret, and bound to the cookie name
 * so one cannot be replayed as the other.
 */
export const PROSPECTUS_PENDING_SIGN_IN_COOKIE = "__Host-papyrus-prospectus-pending";
export const PROSPECTUS_SESSION_COOKIE = "__Host-papyrus-prospectus-session";
export const PROSPECTUS_ACCOUNTS_ENDPOINT_ENV = "PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT";
export const PROSPECTUS_SESSION_SECRET_PARAMETER_ENV = "PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER";
export const PROSPECTUS_SESSION_SECRET_CACHE_MILLISECONDS = 5 * 60 * 1000;

const SEALED_COOKIE_FORMAT_VERSION = "v1";
const SEALED_COOKIE_KEY_DERIVATION_SALT = "papyrus-prospectus-cookie";
const GCM_INITIALIZATION_VECTOR_BYTES = 12;
const GCM_AUTHENTICATION_TAG_BYTES = 16;
const MINIMUM_SEALING_SECRET_LENGTH = 32;

export interface PendingProspectusSignInCookie extends PendingProspectusSignIn {
  returnPath: string;
}

export interface ProspectusSignedInSession {
  personId: string;
  accessToken: string;
  accessTokenExpiresAt: number;
  selectedAccountId?: string;
}

function sealingKeyForCookie(sealingSecret: string, cookieName: string): Buffer {
  if (sealingSecret.length < MINIMUM_SEALING_SECRET_LENGTH) throw new Error("The Prospectus session sealing secret is too short.");
  return Buffer.from(hkdfSync("sha256", sealingSecret, SEALED_COOKIE_KEY_DERIVATION_SALT, cookieName, 32));
}

export function sealProspectusCookie(sealingSecret: string, cookieName: string, payload: object, expiresAtSeconds: number): string {
  const initializationVector = randomBytes(GCM_INITIALIZATION_VECTOR_BYTES);
  const cipher = createCipheriv("aes-256-gcm", sealingKeyForCookie(sealingSecret, cookieName), initializationVector);
  cipher.setAAD(Buffer.from(cookieName));
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify({ payload, expiresAtSeconds })), cipher.final()]);
  return `${SEALED_COOKIE_FORMAT_VERSION}.${Buffer.concat([initializationVector, ciphertext, cipher.getAuthTag()]).toString("base64url")}`;
}

export function openProspectusCookie<Payload>(
  sealingSecret: string,
  cookieName: string,
  sealedValue: string | undefined,
  nowInSeconds: number = Math.floor(Date.now() / 1000),
): Payload | null {
  if (!sealedValue?.startsWith(`${SEALED_COOKIE_FORMAT_VERSION}.`)) return null;
  const sealedBytes = Buffer.from(sealedValue.slice(SEALED_COOKIE_FORMAT_VERSION.length + 1), "base64url");
  if (sealedBytes.length <= GCM_INITIALIZATION_VECTOR_BYTES + GCM_AUTHENTICATION_TAG_BYTES) return null;
  try {
    const decipher = createDecipheriv(
      "aes-256-gcm",
      sealingKeyForCookie(sealingSecret, cookieName),
      sealedBytes.subarray(0, GCM_INITIALIZATION_VECTOR_BYTES),
    );
    decipher.setAAD(Buffer.from(cookieName));
    decipher.setAuthTag(sealedBytes.subarray(sealedBytes.length - GCM_AUTHENTICATION_TAG_BYTES));
    const plaintext = Buffer.concat([
      decipher.update(sealedBytes.subarray(GCM_INITIALIZATION_VECTOR_BYTES, sealedBytes.length - GCM_AUTHENTICATION_TAG_BYTES)),
      decipher.final(),
    ]).toString("utf8");
    const { payload, expiresAtSeconds } = JSON.parse(plaintext) as { payload: Payload; expiresAtSeconds: number };
    if (typeof expiresAtSeconds !== "number" || nowInSeconds >= expiresAtSeconds) return null;
    return payload;
  } catch {
    return null;
  }
}

export function sealedCookieAttributes(expiresAtSeconds: number, nowInSeconds: number = Math.floor(Date.now() / 1000)) {
  return {
    httpOnly: true,
    secure: true,
    sameSite: "lax" as const,
    path: "/",
    maxAge: Math.max(0, expiresAtSeconds - nowInSeconds),
  };
}

export function sameSiteReturnPath(requestedReturnPath: string | null | undefined): string {
  if (!requestedReturnPath || !requestedReturnPath.startsWith("/") || requestedReturnPath.startsWith("//")) return "/";
  if (/[\\\u0000-\u001f]/.test(requestedReturnPath)) return "/";
  const parsed = new URL(requestedReturnPath, "https://papyrus.invalid");
  if (parsed.origin !== "https://papyrus.invalid") return "/";
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

export type ProspectusSessionSecretReader = (parameterName: string) => Promise<string | null>;

type CachedSealingSecret = { parameterName: string; value: string; expiresAt: number };

let cachedSealingSecret: CachedSealingSecret | null = null;
let defaultSsmClient: SSMClient | null = null;

export function resetProspectusSessionSecretCache(): void {
  cachedSealingSecret = null;
}

export async function readSealingSecretFromSsm(parameterName: string, client?: Pick<SSMClient, "send">): Promise<string | null> {
  defaultSsmClient ??= new SSMClient({});
  const response = await (client ?? defaultSsmClient).send(new GetParameterCommand({ Name: parameterName, WithDecryption: true }));
  return response.Parameter?.Value?.trim() || null;
}

export async function loadProspectusSessionSealingSecret(
  options: { environment?: Record<string, string | undefined>; readSecret?: ProspectusSessionSecretReader; now?: number } = {},
): Promise<string | null> {
  const environment = options.environment ?? process.env;
  const parameterName = environment[PROSPECTUS_SESSION_SECRET_PARAMETER_ENV]?.trim();
  if (!parameterName) return null;
  const now = options.now ?? Date.now();
  if (cachedSealingSecret && cachedSealingSecret.parameterName === parameterName && cachedSealingSecret.expiresAt > now) {
    return cachedSealingSecret.value;
  }
  try {
    const value = (await (options.readSecret ?? readSealingSecretFromSsm)(parameterName))?.trim();
    if (!value || value.length < MINIMUM_SEALING_SECRET_LENGTH) return null;
    cachedSealingSecret = { parameterName, value, expiresAt: now + PROSPECTUS_SESSION_SECRET_CACHE_MILLISECONDS };
    return value;
  } catch (error) {
    console.error(`Prospectus session sealing secret could not be read (${error instanceof Error ? error.name : "error"}).`);
    return null;
  }
}

export interface ProspectusSignInRuntime {
  accounts: ProspectusSiteAccounts;
  cognitoClient: GoogleOnlyCognitoClient;
  sealingSecret: string;
}

interface AmplifyOutputsForProspectusSignIn {
  auth?: { user_pool_id?: string; oauth?: { domain?: string } };
  custom?: { prospectusSignIn?: { clientId?: string; callbackPath?: string } | null };
}

export function regionOfProspectusAccountsEndpoint(endpoint: string): string {
  const match = /^[a-z0-9]+\.execute-api\.([a-z0-9-]+)\.amazonaws\.com$/.exec(new URL(endpoint).hostname);
  if (!match) throw new Error("The Prospectus accounts endpoint is not an API Gateway execute-api host.");
  return match[1];
}

export function googleOnlyCognitoClientFromOutputs(
  amplifyOutputs: AmplifyOutputsForProspectusSignIn | null,
  siteOrigin: string,
): GoogleOnlyCognitoClient | null {
  const userPoolId = amplifyOutputs?.auth?.user_pool_id;
  const hostedUiDomain = amplifyOutputs?.auth?.oauth?.domain;
  const prospectusSignIn = amplifyOutputs?.custom?.prospectusSignIn;
  if (!userPoolId || !hostedUiDomain || !prospectusSignIn?.clientId || !prospectusSignIn.callbackPath) return null;
  return {
    hostedUiOrigin: `https://${hostedUiDomain}`,
    userPoolId,
    clientId: prospectusSignIn.clientId,
    redirectUri: new URL(prospectusSignIn.callbackPath, siteOrigin).toString(),
  };
}

export async function resolveProspectusSignInRuntime(
  siteOrigin: string,
  options: {
    environment?: Record<string, string | undefined>;
    amplifyOutputs?: AmplifyOutputsForProspectusSignIn | null;
    readSecret?: ProspectusSessionSecretReader;
    transport?: ProspectusTransport;
  } = {},
): Promise<ProspectusSignInRuntime | null> {
  const environment = options.environment ?? process.env;
  const endpoint = environment[PROSPECTUS_ACCOUNTS_ENDPOINT_ENV]?.trim();
  if (!endpoint) return null;
  const amplifyOutputs = options.amplifyOutputs !== undefined
    ? options.amplifyOutputs
    : (readAmplifyOutputsFile() as AmplifyOutputsForProspectusSignIn | null);
  const cognitoClient = googleOnlyCognitoClientFromOutputs(amplifyOutputs, siteOrigin);
  if (!cognitoClient) return null;
  const sealingSecret = await loadProspectusSessionSealingSecret({ environment, readSecret: options.readSecret });
  if (!sealingSecret) return null;
  const transport = options.transport ?? signedProspectusTransport({ endpoint, region: regionOfProspectusAccountsEndpoint(endpoint) });
  return { accounts: new ProspectusSiteAccounts(transport), cognitoClient, sealingSecret };
}
