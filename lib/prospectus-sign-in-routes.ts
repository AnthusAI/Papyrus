import { NextResponse, type NextRequest } from "next/server";
import {
  CYCLOTRON_LAB_PRODUCT,
  ProspectusAccountsError,
  beginProspectusGoogleSignIn,
  completeProspectusGoogleSignIn,
  type CompleteProspectusGoogleSignInInput,
} from "./prospectus-site-identity";
import {
  PROSPECTUS_PENDING_SIGN_IN_COOKIE,
  PROSPECTUS_SESSION_COOKIE,
  openProspectusCookie,
  resolveProspectusSignInRuntime,
  sameSiteReturnPath,
  sealProspectusCookie,
  sealedCookieAttributes,
  type PendingProspectusSignInCookie,
  type ProspectusSignInRuntime,
  type ProspectusSignedInSession,
} from "./prospectus-session";
import { prospectusSiteProduct, publishingAccountsForSite } from "./prospectus-publication-access";

/**
 * The site's sign-in routes for Prospectus accounts: start (challenge, then the
 * Google-only Cognito redirect), callback (verify, resolve, seal the session),
 * session (who is signed in and which accounts they belong to) and sign-out.
 * Every route answers 503 until the site is registered and configured, so an
 * unregistered deployment never half-signs anyone in.
 */
export interface ProspectusSignInRouteOptions {
  resolveRuntime?: (siteOrigin: string) => Promise<ProspectusSignInRuntime | null>;
  siteProduct?: string | null;
  completionOverrides?: Pick<CompleteProspectusGoogleSignInInput, "verifyCognitoTokens" | "fetcher">;
  nowInSeconds?: () => number;
}

const NO_STORE_HEADERS = { "cache-control": "no-store" };

function currentTimeInSeconds(options: ProspectusSignInRouteOptions): number {
  return options.nowInSeconds?.() ?? Math.floor(Date.now() / 1000);
}

async function signInRuntimeFor(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<ProspectusSignInRuntime | null> {
  return (options.resolveRuntime ?? resolveProspectusSignInRuntime)(request.nextUrl.origin);
}

function signInUnavailableResponse(): NextResponse {
  return NextResponse.json(
    { error: "prospectus_sign_in_unavailable", message: "Sign-in through Prospectus is not configured for this site." },
    { status: 503, headers: NO_STORE_HEADERS },
  );
}

function clearSealedCookie(response: NextResponse, cookieName: string): void {
  response.cookies.set(cookieName, "", sealedCookieAttributes(0, 0));
}

function signInFailedResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: code, message }, { status, headers: NO_STORE_HEADERS });
}

export function signedInProspectusSession(
  request: NextRequest,
  sealingSecret: string,
  nowInSeconds?: number,
): ProspectusSignedInSession | null {
  return openProspectusCookie<ProspectusSignedInSession>(
    sealingSecret,
    PROSPECTUS_SESSION_COOKIE,
    request.cookies.get(PROSPECTUS_SESSION_COOKIE)?.value,
    nowInSeconds,
  );
}

export async function handleProspectusSignInStart(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return signInUnavailableResponse();
  const { authorizationUrl, pendingSignIn } = await beginProspectusGoogleSignIn(runtime.accounts, runtime.cognitoClient);
  const pendingSignInCookie: PendingProspectusSignInCookie = {
    ...pendingSignIn,
    returnPath: sameSiteReturnPath(request.nextUrl.searchParams.get("returnTo")),
  };
  const response = NextResponse.redirect(authorizationUrl, { status: 303, headers: NO_STORE_HEADERS });
  response.cookies.set(
    PROSPECTUS_PENDING_SIGN_IN_COOKIE,
    sealProspectusCookie(runtime.sealingSecret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, pendingSignInCookie, pendingSignIn.expiresAt),
    sealedCookieAttributes(pendingSignIn.expiresAt, currentTimeInSeconds(options)),
  );
  return response;
}

export async function handleProspectusSignInCallback(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return signInUnavailableResponse();
  const nowInSeconds = currentTimeInSeconds(options);
  const pendingSignIn = openProspectusCookie<PendingProspectusSignInCookie>(
    runtime.sealingSecret,
    PROSPECTUS_PENDING_SIGN_IN_COOKIE,
    request.cookies.get(PROSPECTUS_PENDING_SIGN_IN_COOKIE)?.value,
    nowInSeconds,
  );
  const response = await completeCallback(request, runtime, pendingSignIn, options, nowInSeconds);
  clearSealedCookie(response, PROSPECTUS_PENDING_SIGN_IN_COOKIE);
  return response;
}

async function completeCallback(
  request: NextRequest,
  runtime: ProspectusSignInRuntime,
  pendingSignIn: PendingProspectusSignInCookie | null,
  options: ProspectusSignInRouteOptions,
  nowInSeconds: number,
): Promise<NextResponse> {
  if (!pendingSignIn) return signInFailedResponse(401, "sign_in_expired", "This sign-in is no longer pending. Start again.");
  const searchParams = request.nextUrl.searchParams;
  if (searchParams.get("error")) return signInFailedResponse(401, "sign_in_declined", "Google sign-in did not complete.");
  const authorizationCode = searchParams.get("code");
  const returnedState = searchParams.get("state");
  if (!authorizationCode || !returnedState) return signInFailedResponse(400, "sign_in_incomplete", "The sign-in response is missing its code or state.");
  try {
    const signedIn = await completeProspectusGoogleSignIn({
      accounts: runtime.accounts,
      cognitoClient: runtime.cognitoClient,
      pendingSignIn,
      returnedState,
      authorizationCode,
      nowInSeconds,
      ...options.completionOverrides,
    });
    const session: ProspectusSignedInSession = {
      personId: signedIn.person.id,
      accessToken: signedIn.accessToken,
      accessTokenExpiresAt: signedIn.accessTokenExpiresAt,
    };
    const response = NextResponse.redirect(new URL(pendingSignIn.returnPath, request.nextUrl.origin), { status: 303, headers: NO_STORE_HEADERS });
    response.cookies.set(
      PROSPECTUS_SESSION_COOKIE,
      sealProspectusCookie(runtime.sealingSecret, PROSPECTUS_SESSION_COOKIE, session, session.accessTokenExpiresAt),
      sealedCookieAttributes(session.accessTokenExpiresAt, nowInSeconds),
    );
    return response;
  } catch (error) {
    if (error instanceof ProspectusAccountsError) return signInFailedResponse(error.status, error.code, error.message);
    console.error(`Prospectus sign-in failed (${error instanceof Error ? error.name : "error"}).`);
    return signInFailedResponse(401, "sign_in_failed", "Sign-in could not be completed.");
  }
}

export async function handleProspectusSessionRead(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return signInUnavailableResponse();
  const session = signedInProspectusSession(request, runtime.sealingSecret, currentTimeInSeconds(options));
  if (!session) return NextResponse.json({ signedIn: false }, { headers: NO_STORE_HEADERS });
  try {
    const directory = await runtime.accounts.accountDirectory(session.accessToken);
    if (!directory.person || directory.person.id !== session.personId) {
      const response = NextResponse.json({ signedIn: false }, { headers: NO_STORE_HEADERS });
      clearSealedCookie(response, PROSPECTUS_SESSION_COOKIE);
      return response;
    }
    return NextResponse.json(
      {
        signedIn: true,
        person: directory.person,
        accounts: directory.accounts,
        cyclotronLabAccess: directory.accounts.some((account) =>
          account.products.some((product) => product.product === CYCLOTRON_LAB_PRODUCT && product.status === "active"),
        ),
        publishingAccounts: publishingAccountsForSite(
          directory.accounts,
          options.siteProduct !== undefined ? options.siteProduct : prospectusSiteProduct(),
        ),
      },
      { headers: NO_STORE_HEADERS },
    );
  } catch (error) {
    if (error instanceof ProspectusAccountsError && error.status === 401) {
      const response = NextResponse.json({ signedIn: false }, { headers: NO_STORE_HEADERS });
      clearSealedCookie(response, PROSPECTUS_SESSION_COOKIE);
      return response;
    }
    if (error instanceof ProspectusAccountsError) return signInFailedResponse(error.status, error.code, error.message);
    console.error(`Prospectus account directory failed (${error instanceof Error ? error.name : "error"}).`);
    return signInFailedResponse(503, "prospectus_unavailable", "Prospectus could not be reached.");
  }
}

export async function handleProspectusSignOut(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  const signedOutDestination = new URL("/", request.nextUrl.origin);
  const destination = runtime
    ? new URL(
      `/logout?${new URLSearchParams({ client_id: runtime.cognitoClient.clientId, logout_uri: signedOutDestination.toString() })}`,
      runtime.cognitoClient.hostedUiOrigin,
    )
    : signedOutDestination;
  const response = NextResponse.redirect(destination, { status: 303, headers: NO_STORE_HEADERS });
  clearSealedCookie(response, PROSPECTUS_SESSION_COOKIE);
  clearSealedCookie(response, PROSPECTUS_PENDING_SIGN_IN_COOKIE);
  return response;
}
