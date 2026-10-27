
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { SignatureV4 } from "@smithy/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";
import { Sha256 } from "@aws-crypto/sha256-js";
import { CognitoJwtVerifier } from "aws-jwt-verify";
import type { JwksCache } from "aws-jwt-verify/jwk";

/**
 * A Papyrus site's server-side view of Prospectus, the single account service.
 *
 * The site signs requests with its own runtime role (the Amplify SSR compute role
 * registered in Prospectus). People sign in through the site's Google-only Cognito
 * client; Prospectus binds that sign-in to a canonical person through a one-time
 * challenge nonce. Papyrus keeps no account or membership tables: every answer here
 * comes from Prospectus, and publication-level grants are never inferred from an
 * account role.
 */

export type ProspectusRole = "owner" | "admin" | "member" | "viewer";
export type ProspectusOperation = "console:read" | "console:write" | "members:read" | "members:write";

export interface ProspectusPerson {
  id: string;
  createdAt: string;
  siteSubject?: string;
}

export interface ProspectusAccountAuthorization {
  allowed: true;
  accountId: string;
  personId: string;
  product: string;
  role: ProspectusRole;
  operation: ProspectusOperation;
  revision: number;
}

/** One retired reader site subject, from `GET /v1/accounts/site-subjects/retired` (reader sites only). */
export interface ProspectusRetiredSiteSubject {
  siteSubject: string;
  reason: "deleted" | "merged";
  survivingSiteSubject?: string;
  retiredAt: string;
}

export interface ProspectusRetiredSiteSubjectsPage {
  retired: ProspectusRetiredSiteSubject[];
  cursor: string;
  more: boolean;
}

export interface ProspectusDirectoryAccount {
  id: string;
  name: string;
  role: ProspectusRole;
  products: Array<{ product: string; status: "active" | "disabled" }>;
}

export interface ProspectusRequest {
  path: string;
  method: "GET" | "POST";
  body?: unknown;
  humanAccessToken?: string;
  identityToken?: string;
  idempotencyKey?: string;
}

export type ProspectusTransport = (request: ProspectusRequest) => Promise<unknown>;

export class ProspectusAccountsError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface TemporaryRuntimeCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
  expiration?: Date;
}

export interface SignedProspectusTransportOptions {
  endpoint: string;
  region: string;
  runtimeCredentials?: () => Promise<TemporaryRuntimeCredentials>;
  fetcher?: typeof fetch;
}

export function signedProspectusTransport(options: SignedProspectusTransportOptions): ProspectusTransport {
  const endpoint = new URL(options.endpoint);
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
    throw new Error("Use an HTTPS Prospectus accounts endpoint.");
  }
  const runtimeCredentials = options.runtimeCredentials ?? defaultProvider();
  const fetcher = options.fetcher ?? fetch;
  return async ({ path, method, body, humanAccessToken, identityToken, idempotencyKey }) => {
    const credentials = await runtimeCredentials();
    if (!credentials.sessionToken || (credentials.expiration && credentials.expiration.getTime() <= Date.now())) {
      throw new Error("Prospectus calls require the site's temporary runtime credentials; static access keys are refused.");
    }
    const url = new URL(`${endpoint.toString().replace(/\/$/, "")}${path}`);
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const headers: Record<string, string> = {
      host: url.host,
      ...(humanAccessToken ? { "x-prospectus-human-token": humanAccessToken } : {}),
      ...(identityToken ? { "x-prospectus-identity-token": identityToken } : {}),
      ...(idempotencyKey ? { "idempotency-key": idempotencyKey } : {}),
      ...(payload ? { "content-type": "application/json" } : {}),
    };
    const signer = new SignatureV4({ service: "execute-api", region: options.region, credentials, sha256: Sha256 });
    // The query string is part of what API Gateway verifies, so it has to be signed as well as sent.
    const query: Record<string, string> = Object.fromEntries(url.searchParams.entries());
    const signed = await signer.sign(
      new HttpRequest({ protocol: url.protocol, hostname: url.hostname, path: url.pathname, method, headers, body: payload, query }),
    );
    const response = await fetcher(url, { method, headers: signed.headers, body: payload, cache: "no-store", redirect: "error" });
    const responseBody = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ProspectusAccountsError(response.status, responseBody.error ?? "request_failed", responseBody.message ?? "Prospectus request failed.");
    }
    return responseBody;
  };
}

export class ProspectusSiteAccounts {
  constructor(private readonly transport: ProspectusTransport) {}

  requestGoogleSignInChallenge(): Promise<{ challengeId: string; nonce: string; expiresAt: number; challengeToken?: string }> {
    return this.transport({ path: "/v1/identities/google/challenge", method: "POST", body: {} }) as Promise<{
      challengeId: string;
      nonce: string;
      expiresAt: number;
      challengeToken?: string;
    }>;
  }

  /**
   * When Prospectus signs its challenges it stores nothing, so the signed `challengeToken` is the only proof the
   * challenge exists and must be sent back unchanged. Without a token (a service that stores challenges) the ID is sent.
   */
  resolveGoogleSignIn(
    challenge: { challengeId: string; challengeToken?: string },
    humanAccessToken: string,
    identityToken: string,
  ): Promise<{ person: ProspectusPerson }> {
    return this.transport({
      path: "/v1/identities/google/resolve",
      method: "POST",
      body: challenge.challengeToken ? { challengeToken: challenge.challengeToken } : { challengeId: challenge.challengeId },
      humanAccessToken,
      identityToken,
    }) as Promise<{ person: ProspectusPerson }>;
  }

  currentPerson(humanAccessToken: string): Promise<{ person: ProspectusPerson | null }> {
    return this.transport({ path: "/v1/identities/me", method: "GET", humanAccessToken }) as Promise<{ person: ProspectusPerson | null }>;
  }

  authorizeAccountOperation(humanAccessToken: string, accountId: string, operation: ProspectusOperation): Promise<ProspectusAccountAuthorization> {
    return this.transport({
      path: `/v1/accounts/${encodeURIComponent(accountId)}/authorize`,
      method: "POST",
      body: { operation },
      humanAccessToken,
    }) as Promise<ProspectusAccountAuthorization>;
  }

  createAccount(humanAccessToken: string, accountName: string, idempotencyKey: string): Promise<{ account: { id: string; name: string; role: ProspectusRole } }> {
    return this.transport({
      path: "/v1/accounts",
      method: "POST",
      body: { name: accountName },
      humanAccessToken,
      idempotencyKey,
    }) as Promise<{ account: { id: string; name: string; role: ProspectusRole } }>;
  }

  /** The calling site's retired reader subjects since `since` (omit it the first time): at most 100, oldest first. */
  retiredSiteSubjects(since?: string): Promise<ProspectusRetiredSiteSubjectsPage> {
    const query = since ? `?since=${encodeURIComponent(since)}` : "";
    return this.transport({ path: `/v1/accounts/site-subjects/retired${query}`, method: "GET" }) as Promise<ProspectusRetiredSiteSubjectsPage>;
  }

  accountDirectory(humanAccessToken: string): Promise<{ person: ProspectusPerson | null; accounts: ProspectusDirectoryAccount[] }> {
    return this.transport({ path: "/v1/account-directory", method: "GET", humanAccessToken }) as Promise<{
      person: ProspectusPerson | null;
      accounts: ProspectusDirectoryAccount[];
    }>;
  }
}

export interface GoogleOnlyCognitoClient {
  hostedUiOrigin: string;
  userPoolId: string;
  clientId: string;
  redirectUri: string;
}

export interface PendingProspectusSignIn {
  challengeId: string;
  nonce: string;
  /** The signed challenge from Prospectus, present when it signs challenges instead of storing them. */
  challengeToken?: string;
  state: string;
  codeVerifier: string;
  expiresAt: number;
}

export interface CognitoTokens {
  accessToken: string;
  idToken: string;
  refreshToken?: string;
  expiresInSeconds: number;
}

export type CognitoTokenVerifier = (tokens: CognitoTokens, expectedNonce: string) => Promise<void>;

function base64UrlRandom(byteLength: number): string {
  return randomBytes(byteLength).toString("base64url");
}

function constantTimeEquals(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

export async function beginProspectusGoogleSignIn(
  accounts: ProspectusSiteAccounts,
  cognitoClient: GoogleOnlyCognitoClient,
): Promise<{ authorizationUrl: string; pendingSignIn: PendingProspectusSignIn }> {
  const challenge = await accounts.requestGoogleSignInChallenge();
  const state = base64UrlRandom(32);
  const codeVerifier = base64UrlRandom(48);
  const authorizationUrl = new URL("/oauth2/authorize", cognitoClient.hostedUiOrigin);
  authorizationUrl.search = new URLSearchParams({
    response_type: "code",
    client_id: cognitoClient.clientId,
    redirect_uri: cognitoClient.redirectUri,
    scope: "openid email profile",
    identity_provider: "Google",
    state,
    nonce: challenge.nonce,
    code_challenge: createHash("sha256").update(codeVerifier).digest("base64url"),
    code_challenge_method: "S256",
  }).toString();
  return {
    authorizationUrl: authorizationUrl.toString(),
    pendingSignIn: {
      challengeId: challenge.challengeId,
      nonce: challenge.nonce,
      ...(challenge.challengeToken ? { challengeToken: challenge.challengeToken } : {}),
      state, codeVerifier,
      expiresAt: challenge.expiresAt,
    },
  };
}

export function cognitoTokenVerifier(cognitoClient: GoogleOnlyCognitoClient, signingKeyCache?: JwksCache): CognitoTokenVerifier {
  const verifierOptions = signingKeyCache ? { jwksCache: signingKeyCache } : undefined;
  const accessTokenVerifier = CognitoJwtVerifier.create({ userPoolId: cognitoClient.userPoolId, tokenUse: "access", clientId: cognitoClient.clientId }, verifierOptions);
  const identityTokenVerifier = CognitoJwtVerifier.create({ userPoolId: cognitoClient.userPoolId, tokenUse: "id", clientId: cognitoClient.clientId }, verifierOptions);
  return async (tokens, expectedNonce) => {
    const accessClaims = await accessTokenVerifier.verify(tokens.accessToken);
    const identityClaims = await identityTokenVerifier.verify(tokens.idToken);
    if (identityClaims.nonce !== expectedNonce) throw new ProspectusAccountsError(401, "nonce_mismatch", "Sign-in did not carry this site's Prospectus challenge.");
    if (identityClaims.sub !== accessClaims.sub) throw new ProspectusAccountsError(401, "token_pair_mismatch", "Access and identity tokens describe different people.");
  };
}

export interface CompleteProspectusGoogleSignInInput {
  accounts: ProspectusSiteAccounts;
  cognitoClient: GoogleOnlyCognitoClient;
  pendingSignIn: PendingProspectusSignIn;
  returnedState: string;
  authorizationCode: string;
  expectedNewsroomSubject?: string;
  verifyCognitoTokens?: CognitoTokenVerifier;
  fetcher?: typeof fetch;
  nowInSeconds?: number;
}

export async function completeProspectusGoogleSignIn(
  input: CompleteProspectusGoogleSignInInput,
): Promise<{ person: ProspectusPerson; accessToken: string; refreshToken?: string; accessTokenExpiresAt: number }> {
  const nowInSeconds = input.nowInSeconds ?? Math.floor(Date.now() / 1000);
  if (nowInSeconds >= input.pendingSignIn.expiresAt) {
    throw new ProspectusAccountsError(401, "sign_in_expired", "Sign-in took too long. Start again.");
  }
  if (!constantTimeEquals(input.returnedState, input.pendingSignIn.state)) {
    throw new ProspectusAccountsError(401, "state_mismatch", "Sign-in response does not belong to this browser's sign-in.");
  }
  const tokenResponse = await (input.fetcher ?? fetch)(new URL("/oauth2/token", input.cognitoClient.hostedUiOrigin), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: input.cognitoClient.clientId,
      code: input.authorizationCode,
      redirect_uri: input.cognitoClient.redirectUri,
      code_verifier: input.pendingSignIn.codeVerifier,
    }).toString(),
    cache: "no-store",
    redirect: "error",
  });
  const tokenBody = await tokenResponse.json().catch(() => ({}));
  if (!tokenResponse.ok || typeof tokenBody.access_token !== "string" || typeof tokenBody.id_token !== "string") {
    throw new ProspectusAccountsError(401, "code_exchange_failed", "Cognito did not complete the sign-in.");
  }
  const tokens: CognitoTokens = {
    accessToken: tokenBody.access_token,
    idToken: tokenBody.id_token,
    refreshToken: typeof tokenBody.refresh_token === "string" ? tokenBody.refresh_token : undefined,
    expiresInSeconds: Number(tokenBody.expires_in) || 0,
  };
  await (input.verifyCognitoTokens ?? cognitoTokenVerifier(input.cognitoClient))(tokens, input.pendingSignIn.nonce);
  if (input.expectedNewsroomSubject) {
    const claims = JSON.parse(Buffer.from(tokens.accessToken.split(".")[1], "base64url").toString("utf8")) as { sub?: string };
    if (claims.sub !== input.expectedNewsroomSubject) {
      throw new ProspectusAccountsError(403, "newsroom_identity_mismatch", "Continue with the same Google account as your newsroom session.");
    }
  }
  const { person } = await input.accounts.resolveGoogleSignIn(input.pendingSignIn, tokens.accessToken, tokens.idToken);
  return {
    person,
    accessToken: tokens.accessToken,
    refreshToken: tokens.refreshToken,
    accessTokenExpiresAt: nowInSeconds + tokens.expiresInSeconds,
  };
}

export async function authorizeSignedInPersonForAccount(
  accounts: ProspectusSiteAccounts,
  humanAccessToken: string,
  accountId: string,
  operation: ProspectusOperation,
): Promise<ProspectusAccountAuthorization> {
  const { person } = await accounts.currentPerson(humanAccessToken);
  if (!person) throw new ProspectusAccountsError(401, "unknown_person", "Sign in again: Prospectus does not recognize this session.");
  const authorization = await accounts.authorizeAccountOperation(humanAccessToken, accountId, operation);
  if (authorization.allowed !== true || authorization.personId !== person.id || authorization.accountId !== accountId || authorization.operation !== operation) {
    throw new ProspectusAccountsError(403, "not_authorized", "Prospectus did not authorize this account operation.");
  }
  return authorization;
}

export const CYCLOTRON_LAB_PRODUCT = "cyclotron";

export async function signedInPersonHasCyclotronLabAccess(accounts: ProspectusSiteAccounts, humanAccessToken: string): Promise<boolean> {
  const directory = await accounts.accountDirectory(humanAccessToken);
  if (!directory.person) return false;
  return directory.accounts.some((account) =>
    account.products.some((product) => product.product === CYCLOTRON_LAB_PRODUCT && product.status === "active"),
  );
}
