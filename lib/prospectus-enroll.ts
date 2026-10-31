import { createHash } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { CognitoJwtVerifier } from "aws-jwt-verify";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import { ProspectusAccountsError, type GoogleOnlyCognitoClient } from "./prospectus-site-identity";
import { resolveProspectusSignInRuntime, type ProspectusSignInRuntime } from "./prospectus-session";
import { publicSiteOrigin } from "./site-origin";

/**
 * `POST /cli/enroll`: enrolls one `papyrus login --remote` login as a Prospectus Person.
 *
 * The CLI posts the challenge token the approval page bound, its ID token and the broker transaction as the login
 * state, with its access token as the bearer. This route checks both tokens against the site's registered federation
 * client, then asks Prospectus to resolve them as the site. A login made on any other client is refused here before
 * Prospectus is asked, and Prospectus refuses it again. A site answers 404 until it turns enrollment on.
 */
export const CLI_ENROLL_MAXIMUM_BODY_BYTES = 16 * 1024;
const NO_STORE = { "cache-control": "no-store" };
const LOGIN_STATE = /^[A-Za-z0-9_-]{1,128}$/;
const PASSED_THROUGH_CODES = new Set(["challenge_invalid", "login_state", "challenge_replay", "reenrollment_required"]);

export type VerifyEnrollmentTokens = (client: GoogleOnlyCognitoClient, accessToken: string, idToken: string) => Promise<void>;

export interface CliEnrollOptions {
  readOutputs?: () => { custom?: { cliLogin?: { enrollment?: boolean } | null } } | null;
  resolveRuntime?: (siteOrigin: string) => Promise<ProspectusSignInRuntime | null>;
  verifyTokens?: VerifyEnrollmentTokens;
  environment?: Record<string, string | undefined>;
}

function refusal(status: number, error: string, message: string): NextResponse {
  return NextResponse.json({ error, message }, { status, headers: NO_STORE });
}

export const verifyEnrollmentTokens: VerifyEnrollmentTokens = async (client, accessToken, idToken) => {
  const access = await CognitoJwtVerifier.create({ userPoolId: client.userPoolId, tokenUse: "access", clientId: client.clientId }).verify(accessToken);
  const identity = await CognitoJwtVerifier.create({ userPoolId: client.userPoolId, tokenUse: "id", clientId: client.clientId }).verify(idToken);
  if (access.sub !== identity.sub || access.auth_time !== identity.auth_time || typeof identity.auth_time !== "number") {
    throw new Error("The access and ID tokens are not one login.");
  }
};

export async function handleCliEnroll(request: NextRequest, options: CliEnrollOptions = {}): Promise<NextResponse> {
  const outputs = (options.readOutputs ?? (() => readAmplifyOutputsFile() as ReturnType<NonNullable<CliEnrollOptions["readOutputs"]>>))();
  if (outputs?.custom?.cliLogin?.enrollment !== true) {
    return refusal(404, "cli_enrollment_not_configured", "This site has not switched on CLI enrollment.");
  }
  if (request.method !== "POST") return refusal(405, "method_not_allowed", "Use POST.");
  const authorization = request.headers.get("authorization") ?? "";
  const accessToken = /^Bearer ([A-Za-z0-9._-]{1,8192})$/.exec(authorization)?.[1];
  const text = await request.text();
  let body: { challengeToken?: unknown; idToken?: unknown; loginState?: unknown } = {};
  if (Buffer.byteLength(text, "utf8") <= CLI_ENROLL_MAXIMUM_BODY_BYTES) {
    try {
      body = JSON.parse(text);
    } catch {
      body = {};
    }
  }
  const { challengeToken, idToken, loginState } = body;
  if (
    !accessToken
    || typeof challengeToken !== "string" || challengeToken.length === 0 || challengeToken.length > 2048
    || typeof idToken !== "string" || !/^[A-Za-z0-9._-]{1,8192}$/.test(idToken)
    || typeof loginState !== "string" || !LOGIN_STATE.test(loginState)
  ) {
    return refusal(400, "invalid_request", "The enrollment request is not complete.");
  }
  let runtime: ProspectusSignInRuntime | null;
  try {
    runtime = await (options.resolveRuntime ?? resolveProspectusSignInRuntime)(publicSiteOrigin(request, options.environment));
  } catch {
    runtime = null;
  }
  if (!runtime) return refusal(503, "unavailable", "Enrollment is unavailable.");
  try {
    await (options.verifyTokens ?? verifyEnrollmentTokens)(runtime.cognitoClient, accessToken, idToken);
  } catch {
    return refusal(403, "login_not_enrollable", "This login was not made on the site's registered sign-in client.");
  }
  try {
    const { person } = await runtime.accounts.resolveCliEnrollment(challengeToken, loginState, accessToken, idToken);
    return NextResponse.json({ person: { id: person.id } }, { status: 200, headers: NO_STORE });
  } catch (error) {
    if (error instanceof ProspectusAccountsError && PASSED_THROUGH_CODES.has(error.code) && error.status >= 400 && error.status < 500) {
      return refusal(error.status, error.code, "Prospectus refused this enrollment.");
    }
    return refusal(503, "unavailable", "Enrollment is unavailable.");
  }
}

/**
 * `GET /cli/challenge?state=<the CLI's own state>`: the local `papyrus login`'s challenge, bound to `sha256hex(state)`
 * and never unbound. Answers the challenge's nonce and signed token, which the CLI uses as its OpenID nonce and as the
 * enrollment it posts to `/cli/enroll`. Same switch as the enroll route: 404 and nothing called until the site turns
 * enrollment on.
 */
export async function handleCliChallenge(request: NextRequest, options: CliEnrollOptions = {}): Promise<NextResponse> {
  const outputs = (options.readOutputs ?? (() => readAmplifyOutputsFile() as ReturnType<NonNullable<CliEnrollOptions["readOutputs"]>>))();
  if (outputs?.custom?.cliLogin?.enrollment !== true) {
    return refusal(404, "cli_enrollment_not_configured", "This site has not switched on CLI enrollment.");
  }
  if (request.method !== "GET") return refusal(405, "method_not_allowed", "Use GET.");
  const state = request.nextUrl.searchParams.get("state") ?? "";
  if (!LOGIN_STATE.test(state)) return refusal(400, "invalid_request", "The challenge request is not complete.");
  try {
    const runtime = await (options.resolveRuntime ?? resolveProspectusSignInRuntime)(publicSiteOrigin(request, options.environment));
    if (!runtime) return refusal(503, "unavailable", "Enrollment is unavailable.");
    const challenge = await runtime.accounts.requestGoogleSignInChallenge(createHash("sha256").update(state).digest("hex"));
    if (typeof challenge.nonce !== "string" || typeof challenge.challengeToken !== "string") {
      return refusal(503, "unavailable", "Enrollment is unavailable.");
    }
    return NextResponse.json({ nonce: challenge.nonce, challengeToken: challenge.challengeToken }, { status: 200, headers: NO_STORE });
  } catch {
    return refusal(503, "unavailable", "Enrollment is unavailable.");
  }
}
