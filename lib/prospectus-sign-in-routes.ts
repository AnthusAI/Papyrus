import { NextResponse, type NextRequest } from "next/server";
import {
  CYCLOTRON_LAB_PRODUCT,
  ProspectusAccountsError,
  authorizeSignedInPersonForAccount,
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
import {
  prospectusSiteProduct,
  publicationCapabilitiesForProspectusRole,
  publishingAccountsForSite,
  type PublicationCapability,
} from "./prospectus-publication-access";
import { SiteOriginNotConfiguredError, publicSiteOrigin, siteOriginNotConfiguredResponse } from "./site-origin";

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
  /** Trusted configuration the public site origin is read from; defaults to process.env. */
  environment?: Record<string, string | undefined>;
}

const NO_STORE_HEADERS = { "cache-control": "no-store" };

function siteProductFor(options: ProspectusSignInRouteOptions): string | null {
  return options.siteProduct !== undefined ? options.siteProduct : prospectusSiteProduct();
}

function currentTimeInSeconds(options: ProspectusSignInRouteOptions): number {
  return options.nowInSeconds?.() ?? Math.floor(Date.now() / 1000);
}

function siteOriginFor(request: NextRequest, options: ProspectusSignInRouteOptions): string {
  return publicSiteOrigin(request, options.environment);
}

async function signInRuntimeFor(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<ProspectusSignInRuntime | null> {
  return (options.resolveRuntime ?? resolveProspectusSignInRuntime)(siteOriginFor(request, options));
}

/** Runs a route and answers a missing site origin with 503 site_origin_not_configured, never a localhost redirect. */
async function failingClosedWithoutSiteOrigin(route: () => Promise<NextResponse>): Promise<NextResponse> {
  try {
    return await route();
  } catch (error) {
    if (error instanceof SiteOriginNotConfiguredError) return siteOriginNotConfiguredResponse(error);
    throw error;
  }
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

/** A JSON failure, for the routes the page script calls with fetch (session, account selection and creation). */
function signInFailedResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: code, message }, { status, headers: NO_STORE_HEADERS });
}

/**
 * A failed sign-in never leaves the browser on /api/auth/prospectus/callback: it answers 303 to the page the reader started from
 * (or the home page when that is not known) with `sign_in_error=<code>`, which the reader plugin turns into a short message.
 */
function signInFailedRedirect(request: NextRequest, options: ProspectusSignInRouteOptions, returnPath: string | null, code: string): NextResponse {
  const target = new URL(returnPath ?? "/", siteOriginFor(request, options));
  target.searchParams.set("sign_in_error", /^[a-z0-9_]{1,60}$/.test(code) ? code : "sign_in_failed");
  return NextResponse.redirect(target, { status: 303, headers: NO_STORE_HEADERS });
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

/** `returnTo` from the query (a link) or, for the POST form the reader plugin's button submits, from the form body. */
async function requestedReturnPath(request: NextRequest): Promise<string | null> {
  if (request.method !== "POST") return request.nextUrl.searchParams.get("returnTo");
  try {
    const value = (await request.formData()).get("returnTo");
    return typeof value === "string" ? value : null;
  } catch {
    return null;
  }
}

/** GET (a link) or POST (the reader plugin's "Sign in" button, so people are never sent to an /api URL) starts the Google sign-in with a 303 to Google. */
export function handleProspectusSignInStart(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  return failingClosedWithoutSiteOrigin(() => handleProspectusSignInStartRoute(request, options));
}

async function handleProspectusSignInStartRoute(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return signInUnavailableResponse();
  const { authorizationUrl, pendingSignIn } = await beginProspectusGoogleSignIn(runtime.accounts, runtime.cognitoClient);
  const pendingSignInCookie: PendingProspectusSignInCookie = {
    ...pendingSignIn,
    returnPath: sameSiteReturnPath(await requestedReturnPath(request)),
  };
  const response = NextResponse.redirect(authorizationUrl, { status: 303, headers: NO_STORE_HEADERS });
  response.cookies.set(
    PROSPECTUS_PENDING_SIGN_IN_COOKIE,
    sealProspectusCookie(runtime.sealingSecret, PROSPECTUS_PENDING_SIGN_IN_COOKIE, pendingSignInCookie, pendingSignIn.expiresAt),
    sealedCookieAttributes(pendingSignIn.expiresAt, currentTimeInSeconds(options)),
  );
  return response;
}

export function handleProspectusSignInCallback(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  return failingClosedWithoutSiteOrigin(() => handleProspectusSignInCallbackRoute(request, options));
}

async function handleProspectusSignInCallbackRoute(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<NextResponse> {
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
  const failed = (code: string) => signInFailedRedirect(request, options, pendingSignIn?.returnPath ?? null, code);
  if (!pendingSignIn) return failed("sign_in_expired");
  const searchParams = request.nextUrl.searchParams;
  if (searchParams.get("error")) return failed("sign_in_declined");
  const authorizationCode = searchParams.get("code");
  const returnedState = searchParams.get("state");
  if (!authorizationCode || !returnedState) return failed("sign_in_incomplete");
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
      ...(signedIn.person.siteSubject ? { siteSubject: signedIn.person.siteSubject } : {}),
    };
    const response = NextResponse.redirect(new URL(pendingSignIn.returnPath, siteOriginFor(request, options)), { status: 303, headers: NO_STORE_HEADERS });
    response.cookies.set(
      PROSPECTUS_SESSION_COOKIE,
      sealProspectusCookie(runtime.sealingSecret, PROSPECTUS_SESSION_COOKIE, session, session.accessTokenExpiresAt),
      sealedCookieAttributes(session.accessTokenExpiresAt, nowInSeconds),
    );
    return response;
  } catch (error) {
    if (error instanceof ProspectusAccountsError) return failed(error.code);
    console.error(`Prospectus sign-in failed (${error instanceof Error ? error.name : "error"}).`);
    return failed("sign_in_failed");
  }
}

export function handleProspectusSessionRead(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  return failingClosedWithoutSiteOrigin(() => handleProspectusSessionReadRoute(request, options));
}

async function handleProspectusSessionReadRoute(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<NextResponse> {
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
    const publishingAccounts = publishingAccountsForSite(directory.accounts, siteProductFor(options));
    // Only what the UI reads: no person id, siteSubject or account list ever goes to the browser.
    return NextResponse.json(
      {
        signedIn: true,
        cyclotronLabAccess: directory.accounts.some((account) =>
          account.products.some((product) => product.product === CYCLOTRON_LAB_PRODUCT && product.status === "active"),
        ),
        publishingAccounts,
        selectedAccountId: publishingAccounts.some((account) => account.accountId === session.selectedAccountId)
          ? session.selectedAccountId
          : null,
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

export function handleProspectusSignOut(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  return failingClosedWithoutSiteOrigin(() => handleProspectusSignOutRoute(request, options));
}

async function handleProspectusSignOutRoute(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  const signedOutDestination = new URL("/", siteOriginFor(request, options));
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

export interface ProspectusPublishingSelection {
  personId: string;
  accountId: string;
  role: string;
  publicationCapabilities: PublicationCapability[];
}

async function freshlyAuthorizedPublishingSelection(
  runtime: ProspectusSignInRuntime,
  session: ProspectusSignedInSession,
  accountId: string,
  siteProduct: string | null,
): Promise<ProspectusPublishingSelection | null> {
  const directory = await runtime.accounts.accountDirectory(session.accessToken);
  if (!directory.person || directory.person.id !== session.personId) return null;
  if (!publishingAccountsForSite(directory.accounts, siteProduct).some((account) => account.accountId === accountId)) return null;
  const authorization = await authorizeSignedInPersonForAccount(runtime.accounts, session.accessToken, accountId, "console:read");
  if (authorization.personId !== session.personId) return null;
  const publicationCapabilities = publicationCapabilitiesForProspectusRole(authorization.role);
  if (publicationCapabilities.length === 0) return null;
  return { personId: session.personId, accountId, role: authorization.role, publicationCapabilities };
}

export async function currentProspectusPublishingSelection(
  request: NextRequest,
  options: ProspectusSignInRouteOptions = {},
): Promise<ProspectusPublishingSelection | null> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return null;
  const session = signedInProspectusSession(request, runtime.sealingSecret, currentTimeInSeconds(options));
  if (!session?.selectedAccountId) return null;
  try {
    return await freshlyAuthorizedPublishingSelection(runtime, session, session.selectedAccountId, siteProductFor(options));
  } catch (error) {
    if (error instanceof ProspectusAccountsError) return null;
    throw error;
  }
}

export function handleProspectusAccountSelection(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  return failingClosedWithoutSiteOrigin(() => handleProspectusAccountSelectionRoute(request, options));
}

async function handleProspectusAccountSelectionRoute(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return signInUnavailableResponse();
  if (request.headers.get("origin") !== siteOriginFor(request, options)) {
    return signInFailedResponse(403, "cross_origin_selection", "Choose an account from this site.");
  }
  const nowInSeconds = currentTimeInSeconds(options);
  const session = signedInProspectusSession(request, runtime.sealingSecret, nowInSeconds);
  if (!session) return signInFailedResponse(401, "signed_out", "Sign in first.");
  const body = await request.json().catch(() => null) as { accountId?: unknown } | null;
  const accountId = typeof body?.accountId === "string" ? body.accountId.trim() : "";
  if (!accountId) return signInFailedResponse(400, "account_required", "Choose an account.");
  try {
    const selection = await freshlyAuthorizedPublishingSelection(runtime, session, accountId, siteProductFor(options));
    if (!selection) return signInFailedResponse(403, "not_a_publishing_account", "You cannot work on this site's publications in that account.");
    const response = NextResponse.json(
      { selectedAccountId: selection.accountId, role: selection.role, publicationCapabilities: selection.publicationCapabilities },
      { headers: NO_STORE_HEADERS },
    );
    const selectedSession: ProspectusSignedInSession = { ...session, selectedAccountId: selection.accountId };
    response.cookies.set(
      PROSPECTUS_SESSION_COOKIE,
      sealProspectusCookie(runtime.sealingSecret, PROSPECTUS_SESSION_COOKIE, selectedSession, session.accessTokenExpiresAt),
      sealedCookieAttributes(session.accessTokenExpiresAt, nowInSeconds),
    );
    return response;
  } catch (error) {
    if (error instanceof ProspectusAccountsError) return signInFailedResponse(error.status, error.code, error.message);
    console.error(`Prospectus account selection failed (${error instanceof Error ? error.name : "error"}).`);
    return signInFailedResponse(503, "prospectus_unavailable", "Prospectus could not be reached.");
  }
}

const MAXIMUM_PUBLISHING_ACCOUNT_NAME_LENGTH = 150;
const DEFAULT_PUBLISHING_ACCOUNT_NAME = "Publishing account";
const IDEMPOTENCY_KEY_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function handleProspectusPublishingAccountCreation(request: NextRequest, options: ProspectusSignInRouteOptions = {}): Promise<NextResponse> {
  return failingClosedWithoutSiteOrigin(() => handleProspectusPublishingAccountCreationRoute(request, options));
}

async function handleProspectusPublishingAccountCreationRoute(request: NextRequest, options: ProspectusSignInRouteOptions): Promise<NextResponse> {
  const runtime = await signInRuntimeFor(request, options);
  if (!runtime) return signInUnavailableResponse();
  if (request.headers.get("origin") !== siteOriginFor(request, options)) {
    return signInFailedResponse(403, "cross_origin_creation", "Create an account from this site.");
  }
  const nowInSeconds = currentTimeInSeconds(options);
  const session = signedInProspectusSession(request, runtime.sealingSecret, nowInSeconds);
  if (!session) return signInFailedResponse(401, "signed_out", "Sign in first.");
  const body = await request.json().catch(() => null) as { name?: unknown; idempotencyKey?: unknown } | null;
  const requestedName = typeof body?.name === "string" ? body.name.trim() : "";
  const accountName = requestedName || DEFAULT_PUBLISHING_ACCOUNT_NAME;
  if (accountName.length > MAXIMUM_PUBLISHING_ACCOUNT_NAME_LENGTH) {
    return signInFailedResponse(400, "account_name_too_long", "Name the account in 150 characters or fewer.");
  }
  const idempotencyKey = typeof body?.idempotencyKey === "string" ? body.idempotencyKey : "";
  if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
    return signInFailedResponse(400, "idempotency_key_required", "Send a UUID idempotency key.");
  }
  try {
    const created = await runtime.accounts.createAccount(session.accessToken, accountName, idempotencyKey);
    const selection = await freshlyAuthorizedPublishingSelection(runtime, session, created.account.id, siteProductFor(options));
    if (!selection) return signInFailedResponse(403, "not_a_publishing_account", "The new account does not grant publishing access on this site.");
    const response = NextResponse.json(
      { selectedAccountId: selection.accountId, role: selection.role, publicationCapabilities: selection.publicationCapabilities },
      { status: 201, headers: NO_STORE_HEADERS },
    );
    const selectedSession: ProspectusSignedInSession = { ...session, selectedAccountId: selection.accountId };
    response.cookies.set(
      PROSPECTUS_SESSION_COOKIE,
      sealProspectusCookie(runtime.sealingSecret, PROSPECTUS_SESSION_COOKIE, selectedSession, session.accessTokenExpiresAt),
      sealedCookieAttributes(session.accessTokenExpiresAt, nowInSeconds),
    );
    return response;
  } catch (error) {
    if (error instanceof ProspectusAccountsError) return signInFailedResponse(error.status, error.code, error.message);
    console.error(`Prospectus account creation failed (${error instanceof Error ? error.name : "error"}).`);
    return signInFailedResponse(503, "prospectus_unavailable", "Prospectus could not be reached.");
  }
}
