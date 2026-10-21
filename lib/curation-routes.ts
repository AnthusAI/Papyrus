import { NextResponse, type NextRequest } from "next/server";
import { SITE_BRAND } from "./site-brand";
import type { PublicationCapability } from "./prospectus-publication-access";
import {
  currentProspectusPublishingSelection,
  signedInProspectusSession,
  type ProspectusPublishingSelection,
  type ProspectusSignInRouteOptions,
} from "./prospectus-sign-in-routes";
import { resolveProspectusSignInRuntime } from "./prospectus-session";

/**
 * Same-origin curation routes for the References tab. Each is an authenticated
 * pass-through to the curation upstream (the central Cyclotron lab): this
 * module decides who may call and what they may ask, the upstream repeats its
 * own checks, and neither trusts the browser's pins as identity.
 *
 * Order, failing closed at each step: upstream configured, Origin and body,
 * sealed session cookie, fresh Prospectus re-authorization, scope pins,
 * capability, forward, then re-authorize again and verify the echoed scope
 * before any byte of the answer reaches the browser.
 */
export const CURATION_UPSTREAM_URL_ENV = "PAPYRUS_CURATION_UPSTREAM_URL";
export const CURATION_PUBLICATION_ID_ENV = "PAPYRUS_CURATION_PUBLICATION_ID";
export const CURATION_MAXIMUM_REQUEST_BYTES = 4_000_000;
export const CURATION_MAXIMUM_RESPONSE_BYTES = 8_000_000;
export const CURATION_UPSTREAM_TIMEOUT_MILLISECONDS = 15_000;

export type CurationRoute = "context" | "publication" | "priming";

export interface CurationRouteOptions extends ProspectusSignInRouteOptions {
  /** Overrides PAPYRUS_CURATION_UPSTREAM_URL. null means not configured. */
  upstreamUrl?: string | null;
  /** Overrides PAPYRUS_CURATION_PUBLICATION_ID, which defaults to the site brand id. */
  publicationId?: string;
  fetcher?: typeof fetch;
  timeoutMilliseconds?: number;
}

const NO_STORE_HEADERS = { "cache-control": "no-store", "x-content-type-options": "nosniff" };
const PIN_HEADERS = ["x-cyclotron-account", "x-papyrus-publication", "x-papyrus-binding"] as const;
const PUBLICATION_OPERATION_CAPABILITIES: Record<string, PublicationCapability> = {
  decide: "decide",
  review: "review",
  status: "read",
  history: "read",
  events: "read",
  replay: "read",
  steer: "steer",
};
const FORWARDED_UPSTREAM_REFUSALS = new Set([400, 403, 409, 413, 415]);

class CurationRefusal extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

function refusal(status: number, code: string, message: string): CurationRefusal {
  return new CurationRefusal(status, code, message);
}

function jsonResponse(body: unknown, status = 200, extraHeaders: Record<string, string> = {}): NextResponse {
  return NextResponse.json(body, { status, headers: { ...NO_STORE_HEADERS, ...extraHeaders } });
}

function upstreamBase(options: CurationRouteOptions): URL | null {
  const configured = options.upstreamUrl !== undefined ? options.upstreamUrl : process.env[CURATION_UPSTREAM_URL_ENV];
  if (!configured?.trim()) return null;
  try {
    const url = new URL(configured.trim());
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.protocol !== "https:" && !(loopback && url.protocol === "http:")) return null;
    if (url.username || url.password) return null;
    return url;
  } catch {
    return null;
  }
}

function publicationIdFor(options: CurationRouteOptions): string {
  return options.publicationId ?? (process.env[CURATION_PUBLICATION_ID_ENV]?.trim() || SITE_BRAND.id);
}

/** Which capability a priming GraphQL document needs. Any hint of a mutation requires review. */
export function primingCapability(query: string): PublicationCapability {
  return /\bmutation\b|\bprimingCommand\b/i.test(query) ? "review" : "read";
}

async function boundedText(request: NextRequest): Promise<string> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > CURATION_MAXIMUM_REQUEST_BYTES) throw refusal(413, "request_too_large", "Curation request exceeds the size limit.");
  const text = await request.text();
  if (Buffer.byteLength(text) > CURATION_MAXIMUM_REQUEST_BYTES) throw refusal(413, "request_too_large", "Curation request exceeds the size limit.");
  return text;
}

async function boundedResponseText(response: Response): Promise<string> {
  const declared = Number(response.headers.get("content-length") ?? "0");
  if (declared > CURATION_MAXIMUM_RESPONSE_BYTES) throw refusal(502, "upstream_response_too_large", "The curation service answered too much.");
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > CURATION_MAXIMUM_RESPONSE_BYTES) {
      await reader.cancel();
      throw refusal(502, "upstream_response_too_large", "The curation service answered too much.");
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function sameSelection(left: ProspectusPublishingSelection, right: ProspectusPublishingSelection | null): boolean {
  return right !== null
    && left.personId === right.personId
    && left.accountId === right.accountId
    && left.role === right.role
    && left.publicationCapabilities.join() === right.publicationCapabilities.join();
}

interface ParsedRequest {
  capability: PublicationCapability;
  /** Raw body to forward; undefined for the context read. */
  body?: string;
}

function parseRequest(route: CurationRoute, text: string | null): ParsedRequest {
  if (route === "context") return { capability: "read" };
  let value: unknown;
  try {
    value = JSON.parse(text ?? "");
  } catch {
    throw refusal(400, "invalid_request", "A JSON curation request is required.");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw refusal(400, "invalid_request", "A JSON curation request is required.");
  const body = value as Record<string, unknown>;
  if (route === "publication") {
    const keys = Object.keys(body).sort().join();
    const operation = typeof body.operation === "string" ? body.operation : "";
    if (keys !== "operation,payload" || !Object.hasOwn(PUBLICATION_OPERATION_CAPABILITIES, operation) || !body.payload || typeof body.payload !== "object" || Array.isArray(body.payload)) {
      throw refusal(400, "invalid_request", "An explicit publication operation is required.");
    }
    return { capability: PUBLICATION_OPERATION_CAPABILITIES[operation], body: text! };
  }
  const variablesValid = body.variables === undefined || (body.variables !== null && typeof body.variables === "object" && !Array.isArray(body.variables));
  if (typeof body.query !== "string" || !body.query.trim() || !variablesValid || Object.keys(body).some((key) => key !== "query" && key !== "variables")) {
    throw refusal(400, "invalid_request", "An explicit priming query is required.");
  }
  return { capability: primingCapability(body.query), body: text! };
}

function requestPins(request: NextRequest, selection: ProspectusPublishingSelection, publicationId: string): Record<(typeof PIN_HEADERS)[number], string> {
  const pins = Object.fromEntries(PIN_HEADERS.map((name) => [name, request.headers.get(name)?.trim() ?? ""])) as Record<(typeof PIN_HEADERS)[number], string>;
  if (PIN_HEADERS.some((name) => !pins[name])) throw refusal(400, "pins_required", "Expected account, publication and binding pins are required.");
  if (pins["x-cyclotron-account"] !== selection.accountId || pins["x-papyrus-publication"] !== publicationId) {
    throw refusal(409, "account_changed", "The selected account or publication changed. Refresh and try again.");
  }
  return pins;
}

function authorizedCapabilities(selection: ProspectusPublishingSelection): PublicationCapability[] {
  return selection.publicationCapabilities;
}

async function forward(
  request: NextRequest,
  route: CurationRoute,
  base: URL,
  options: CurationRouteOptions,
  accessToken: string,
  upstreamHeaders: Record<string, string>,
  body: string | undefined,
): Promise<Response> {
  const target = new URL(`/api/newsroom/curation/${route}`, base);
  const headers: Record<string, string> = {
    ...upstreamHeaders,
    authorization: `Bearer ${accessToken}`,
    accept: "application/json",
  };
  if (body !== undefined) headers["content-type"] = "application/json";
  const response = await (options.fetcher ?? fetch)(target, {
    method: route === "context" ? "GET" : "POST",
    headers,
    body,
    redirect: "manual",
    cache: "no-store",
    signal: AbortSignal.timeout(options.timeoutMilliseconds ?? CURATION_UPSTREAM_TIMEOUT_MILLISECONDS),
  });
  if (response.status >= 300 && response.status < 400) throw refusal(502, "upstream_redirect", "The curation service redirected, which is refused.");
  return response;
}

function sanitizedUpstreamRefusal(status: number, text: string): CurationRefusal {
  try {
    const parsed = JSON.parse(text) as { error?: unknown; code?: unknown };
    const message = typeof parsed.error === "string" ? parsed.error.slice(0, 300) : "The curation service refused the request.";
    const code = typeof parsed.code === "string" ? parsed.code.slice(0, 80) : "upstream_refused";
    return refusal(status, code, message);
  } catch {
    return refusal(status, "upstream_refused", "The curation service refused the request.");
  }
}

function contextBootstrap(value: unknown, selection: ProspectusPublishingSelection, publicationId: string): Record<string, unknown> {
  const body = value as { scope?: Record<string, unknown>; mode?: unknown; priming?: unknown; capabilities?: unknown; bindingRef?: unknown } | null;
  const scope = body?.scope;
  if (!scope || scope.accountId !== selection.accountId || scope.publicationId !== publicationId
    || typeof scope.bindingRevision !== "string" || !scope.bindingRevision
    || (body!.mode !== "embedded" && body!.mode !== "remote") || !Array.isArray(body!.capabilities)) {
    throw refusal(502, "upstream_scope_mismatch", "The curation service answered for a different scope.");
  }
  const granted = new Set<string>(authorizedCapabilities(selection));
  return {
    scope: { accountId: scope.accountId, publicationId: scope.publicationId, bindingRevision: scope.bindingRevision },
    mode: body!.mode,
    priming: body!.priming ?? null,
    capabilities: body!.capabilities.filter((capability): capability is string => typeof capability === "string" && granted.has(capability)),
    bindingRef: body!.bindingRef ?? null,
  };
}

function verifiedPublicationEnvelope(value: unknown, pins: Record<string, string>): void {
  const envelope = value as Record<string, unknown> | null;
  if (!envelope || envelope.contractVersion !== "cyclotron-publication/v1"
    || envelope.accountId !== pins["x-cyclotron-account"]
    || envelope.publicationId !== pins["x-papyrus-publication"]
    || envelope.bindingRevision !== pins["x-papyrus-binding"]) {
    throw refusal(502, "upstream_scope_mismatch", "The curation service answered for a different scope.");
  }
}

export async function handleCurationRoute(request: NextRequest, route: CurationRoute, options: CurationRouteOptions = {}): Promise<NextResponse> {
  try {
    const base = upstreamBase(options);
    if (!base) return jsonResponse({ error: "curation_not_configured", message: "Curation is not configured for this site." }, 503);

    const origin = request.headers.get("origin");
    if (route !== "context" ? origin !== request.nextUrl.origin : origin !== null && origin !== request.nextUrl.origin) {
      throw refusal(403, "cross_origin", "Curation requests must come from this site.");
    }
    let text: string | null = null;
    if (route !== "context") {
      if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") throw refusal(415, "json_required", "A JSON request is required.");
      text = await boundedText(request);
    }

    const runtime = await (options.resolveRuntime ?? resolveProspectusSignInRuntime)(request.nextUrl.origin);
    if (!runtime) return jsonResponse({ error: "prospectus_sign_in_unavailable", message: "Sign-in through Prospectus is not configured for this site." }, 503);
    const nowInSeconds = options.nowInSeconds?.();
    const cookieSession = signedInProspectusSession(request, runtime.sealingSecret, nowInSeconds);
    if (!cookieSession?.selectedAccountId) throw refusal(401, "signed_out", "Sign in and choose an account first.");

    const selection = await currentProspectusPublishingSelection(request, options);
    if (!selection || selection.accountId !== cookieSession.selectedAccountId) throw refusal(403, "not_authorized", "Your account no longer grants access.");

    const publicationId = publicationIdFor(options);
    const pins = route === "context" ? null : requestPins(request, selection, publicationId);
    const parsed = parseRequest(route, text);
    if (!authorizedCapabilities(selection).includes(parsed.capability)) throw refusal(403, "capability_refused", "Your role does not allow this curation action.");

    // The token is read from the sealed cookie again for this call, never held across calls.
    const fresh = signedInProspectusSession(request, runtime.sealingSecret, nowInSeconds);
    if (!fresh || fresh.selectedAccountId !== selection.accountId) throw refusal(401, "signed_out", "Sign in and choose an account first.");
    const upstreamHeaders = pins ?? { "x-cyclotron-account": selection.accountId, "x-papyrus-publication": publicationId };
    const upstream = await forward(request, route, base, options, fresh.accessToken, upstreamHeaders, parsed.body);
    const upstreamText = await boundedResponseText(upstream);
    if (upstream.status !== 200) {
      if (FORWARDED_UPSTREAM_REFUSALS.has(upstream.status)) throw sanitizedUpstreamRefusal(upstream.status, upstreamText);
      throw refusal(502, "upstream_failed", "The curation service could not complete the request. Check saved history before retrying.");
    }

    // Post-upstream check: nothing is released if authority or scope moved while we waited.
    if (!sameSelection(selection, await currentProspectusPublishingSelection(request, options))) {
      throw refusal(409, "account_changed", "The selected account or access changed. Refresh and try again.");
    }
    let answer: unknown;
    try {
      answer = JSON.parse(upstreamText);
    } catch {
      throw refusal(502, "upstream_invalid", "The curation service answered with an invalid response.");
    }
    if (pins) {
      if (PIN_HEADERS.some((name) => upstream.headers.get(name) !== pins[name])) {
        throw refusal(502, "upstream_scope_mismatch", "The curation service answered for a different scope.");
      }
      if (route === "publication") verifiedPublicationEnvelope(answer, pins);
      if (route === "priming" && (!answer || typeof answer !== "object" || Array.isArray(answer))) {
        throw refusal(502, "upstream_invalid", "The curation service answered with an invalid response.");
      }
      return jsonResponse(answer, 200, pins);
    }
    return jsonResponse(contextBootstrap(answer, selection, publicationId));
  } catch (error) {
    if (error instanceof CurationRefusal) return jsonResponse({ error: error.message, code: error.code }, error.status);
    console.error(`Curation route failed (${error instanceof Error ? error.name : "error"}).`);
    return jsonResponse({ error: "Curation is unavailable. Check saved history before retrying.", code: "curation_unavailable" }, 503);
  }
}
