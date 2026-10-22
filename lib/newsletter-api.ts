import { isIP } from "node:net";
import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import {
  confirmPromptPage,
  confirmedPage,
  expiredPage,
  pageResponse,
  pageTheme,
  unavailablePage,
  type PageContent,
} from "./newsletter-pages";
import { PROSPECTUS_SESSION_COOKIE, loadProspectusSessionSealingSecret } from "./prospectus-session";
import { signedInProspectusSession } from "./prospectus-sign-in-routes";
import { readerSubject } from "./reader-subject";
import { SiteOriginNotConfiguredError, publicSiteOrigin, publicSiteUrl, siteOriginNotConfiguredResponse } from "./site-origin";

export const NEWSLETTER_FUNCTION_ENV = "PAPYRUS_NEWSLETTER_FUNCTION";
export const NEWSLETTER_SUBSCRIBE_MAXIMUM_BODY_BYTES = 8192;
export const NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES = 4096;
export const NEWSLETTER_USER_AGENT_CHARACTERS = 300;
export const NEWSLETTER_TOKEN = /^[A-Za-z0-9._-]{1,2048}$/;
const MAXIMUM_LISTS = 20;
const LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;

export type NewsletterEvent = { action: "subscribe" | "confirm" | "confirm_page_state" } & Record<string, unknown>;
export interface NewsletterResult {
  statusCode: number;
  body: Record<string, unknown>;
}
export type NewsletterInvoker = (functionName: string, event: NewsletterEvent) => Promise<NewsletterResult>;

export interface NewsletterApiOptions {
  environment?: Record<string, string | undefined>;
  invoke?: NewsletterInvoker;
  /** The parsed `amplify_outputs.json`; read from disk when absent. */
  outputs?: Record<string, unknown> | null;
  loadSealingSecret?: () => Promise<string | null>;
  nowInSeconds?: number;
}

const NO_STORE = { "cache-control": "no-store" };

function failure(status: number, error: string, message: string): NextResponse {
  return NextResponse.json({ error, message }, { status, headers: NO_STORE });
}

export async function invokeNewsletterLambda(functionName: string, event: NewsletterEvent): Promise<NewsletterResult> {
  const { InvokeCommand, LambdaClient } = await import("@aws-sdk/client-lambda");
  const response = await new LambdaClient({}).send(
    new InvokeCommand({ FunctionName: functionName, InvocationType: "RequestResponse", Payload: Buffer.from(JSON.stringify(event)) }),
  );
  if (response.FunctionError || !response.Payload) throw new Error("newsletter failed");
  const result = JSON.parse(Buffer.from(response.Payload).toString("utf8")) as Partial<NewsletterResult>;
  if (typeof result.statusCode !== "number" || typeof result.body !== "object" || result.body === null) {
    throw new Error("newsletter returned an unexpected shape");
  }
  return { statusCode: result.statusCode, body: result.body as Record<string, unknown> };
}

type Enabled = { settings: Record<string, unknown>; functionName: string | null };

function enabledPlugin(options: NewsletterApiOptions, environment: Record<string, string | undefined>): Enabled | null {
  let outputs: Record<string, unknown> | null;
  try {
    outputs = options.outputs !== undefined ? options.outputs : readAmplifyOutputsFile();
  } catch {
    return null;
  }
  const custom = (outputs as { custom?: { papyrusPlugins?: Record<string, unknown>; newsletter?: { actionsFunction?: unknown } } } | null)?.custom;
  const settings = custom?.papyrusPlugins?.newsletter;
  if (typeof settings !== "object" || settings === null) return null;
  const fromEnvironment = (environment[NEWSLETTER_FUNCTION_ENV] ?? "").trim();
  const fromOutputs = custom?.newsletter?.actionsFunction;
  const functionName = fromEnvironment || (typeof fromOutputs === "string" && fromOutputs.trim() ? fromOutputs.trim() : null);
  return { settings: settings as Record<string, unknown>, functionName };
}

function notFoundJson(): NextResponse {
  return failure(404, "not_found", "Not found.");
}

function notFoundPage(): NextResponse {
  return new NextResponse("Not found", { status: 404, headers: { ...NO_STORE, "content-type": "text/plain; charset=utf-8" } });
}

/** The visitor's address from CloudFront's `ip:port` header (IPv6 may be bracketed), else the first x-forwarded-for entry. */
export function clientAddress(headers: Pick<Headers, "get">): string {
  const viewer = (headers.get("cloudfront-viewer-address") ?? "").trim();
  if (viewer) {
    let candidate: string;
    if (viewer.startsWith("[")) candidate = viewer.slice(1, Math.max(viewer.indexOf("]"), 1));
    else if (isIP(viewer) === 4) candidate = viewer;
    else candidate = viewer.slice(0, Math.max(viewer.lastIndexOf(":"), 0));
    if (isIP(candidate)) return candidate;
  }
  const forwarded = (headers.get("x-forwarded-for") ?? "").split(",")[0]?.trim() ?? "";
  return isIP(forwarded) ? forwarded : "unknown";
}

async function readBody(request: NextRequest, maximum: number, contentTypes: string[]): Promise<{ text: string } | { response: NextResponse }> {
  const contentType = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (!contentTypes.includes(contentType)) return { response: failure(415, "unsupported_media_type", `Send ${contentTypes.join(" or ")}.`) };
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > maximum) return { response: failure(413, "payload_too_large", "The request body is too large.") };
  const text = await request.text();
  if (Buffer.byteLength(text, "utf8") > maximum) return { response: failure(413, "payload_too_large", "The request body is too large.") };
  return { text };
}

function listIds(raw: unknown): string[] {
  const entries = typeof raw === "string" ? raw.slice(0, 1000).split(",") : Array.isArray(raw) ? raw : [];
  return entries
    .filter((entry): entry is string => typeof entry === "string")
    .map((entry) => entry.trim())
    .filter((entry) => LIST_ID.test(entry))
    .slice(0, MAXIMUM_LISTS);
}

function limited(value: unknown, maximum: number): string {
  return typeof value === "string" ? value.slice(0, maximum) : "";
}

/** The reader's pairwise site subject when they happen to be signed in; never required, never logged, never an error. */
async function optionalSiteSubject(request: NextRequest, options: NewsletterApiOptions, environment: Record<string, string | undefined>): Promise<string | undefined> {
  if (!request.cookies.has(PROSPECTUS_SESSION_COOKIE)) return undefined;
  try {
    const sealingSecret = await (options.loadSealingSecret ?? (() => loadProspectusSessionSealingSecret({ environment })))();
    if (!sealingSecret) return undefined;
    const session = signedInProspectusSession(request, sealingSecret, options.nowInSeconds);
    return readerSubject(session, environment) ?? undefined;
  } catch {
    return undefined;
  }
}

function siteOriginOrResponse(request: NextRequest, environment: Record<string, string | undefined>): { origin: string } | { response: NextResponse } {
  try {
    return { origin: publicSiteOrigin(request, environment) };
  } catch (error) {
    if (error instanceof SiteOriginNotConfiguredError) return { response: siteOriginNotConfiguredResponse(error) };
    throw error;
  }
}

/** POST /api/newsletter/subscribe */
export async function handleNewsletterSubscribe(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundJson();
  const site = siteOriginOrResponse(request, environment);
  if ("response" in site) return site.response;
  if (request.headers.get("origin") !== site.origin) return failure(403, "origin_mismatch", "This request did not come from this site.");
  const body = await readBody(request, NEWSLETTER_SUBSCRIBE_MAXIMUM_BODY_BYTES, ["application/json"]);
  if ("response" in body) return body.response;
  let payload: Record<string, unknown>;
  try {
    const parsed = JSON.parse(body.text) as unknown;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("not an object");
    payload = parsed as Record<string, unknown>;
  } catch {
    return failure(400, "invalid_json", "The request body is not a JSON object.");
  }
  if (!plugin.functionName) return failure(503, "newsletter_unavailable", "Newsletter signup is not available right now.");

  const siteSubject = await optionalSiteSubject(request, options, environment);
  const event: NewsletterEvent = {
    action: "subscribe",
    email: limited(payload.email, 320),
    lists: listIds(payload.lists),
    page: limited(payload.page, 500),
    consent: limited(payload.consent, 500),
    formId: limited(payload.formId, 100),
    honeypot: limited(payload.website, 200),
    renderedAt: typeof payload.renderedAt === "number" || typeof payload.renderedAt === "string" ? payload.renderedAt : null,
    ip: clientAddress(request.headers),
    userAgent: limited(request.headers.get("user-agent"), NEWSLETTER_USER_AGENT_CHARACTERS),
    ...(siteSubject ? { siteSubject } : {}),
  };
  try {
    const result = await (options.invoke ?? invokeNewsletterLambda)(plugin.functionName, event);
    const status = typeof result.body.status === "string" ? result.body.status : "error";
    return NextResponse.json({ status }, { status: result.statusCode, headers: NO_STORE });
  } catch (error) {
    console.error(`Newsletter subscribe failed (${error instanceof Error ? error.name : "error"}).`);
    return failure(502, "newsletter_unavailable", "Newsletter signup could not be reached.");
  }
}

function pageBase(plugin: Enabled): Pick<PageContent, "siteName" | "theme"> {
  const fromName = plugin.settings.fromName;
  return { siteName: typeof fromName === "string" && fromName ? fromName : "this site", theme: pageTheme(plugin.settings.theme) };
}

function configuredListNames(plugin: Enabled, ids: string[]): string[] {
  const known = Array.isArray(plugin.settings.lists) ? (plugin.settings.lists as Array<{ id?: unknown; name?: unknown }>) : [];
  return ids.flatMap((id) => {
    const match = known.find((entry) => entry.id === id);
    return typeof match?.name === "string" ? [match.name] : [];
  });
}

/** GET /api/newsletter/confirm?t=... shows the confirm button and never changes state; ?done=1&l=... shows the result. */
export async function handleNewsletterConfirmPage(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundPage();
  const base = pageBase(plugin);
  const params = request.nextUrl.searchParams;
  if (params.get("done") === "1") return pageResponse(confirmedPage(base, configuredListNames(plugin, listIds(params.get("l") ?? ""))));
  const token = params.get("t") ?? "";
  if (!NEWSLETTER_TOKEN.test(token)) return pageResponse(expiredPage(base), 410);
  if (!plugin.functionName) return pageResponse(unavailablePage(base), 503);
  try {
    const result = await (options.invoke ?? invokeNewsletterLambda)(plugin.functionName, { action: "confirm_page_state", token });
    if (result.body.status !== "ready") return pageResponse(expiredPage(base), 410);
    const lists = Array.isArray(result.body.lists) ? (result.body.lists as Array<{ name?: unknown }>) : [];
    const names = lists.flatMap((entry) => (typeof entry.name === "string" ? [entry.name] : []));
    return pageResponse(confirmPromptPage(base, names, token));
  } catch (error) {
    console.error(`Newsletter confirm page failed (${error instanceof Error ? error.name : "error"}).`);
    return pageResponse(unavailablePage(base), 502);
  }
}

/** POST /api/newsletter/confirm (form field `t`) confirms, then redirects with 303 to the result page. */
export async function handleNewsletterConfirmPost(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundPage();
  const base = pageBase(plugin);
  const site = siteOriginOrResponse(request, environment);
  if ("response" in site) return site.response;
  if (request.headers.get("origin") !== site.origin) return failure(403, "origin_mismatch", "This request did not come from this site.");
  const body = await readBody(request, NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES, ["application/x-www-form-urlencoded"]);
  if ("response" in body) return body.response;
  const token = new URLSearchParams(body.text).get("t") ?? "";
  if (!NEWSLETTER_TOKEN.test(token)) return pageResponse(expiredPage(base), 410);
  if (!plugin.functionName) return pageResponse(unavailablePage(base), 503);
  try {
    const result = await (options.invoke ?? invokeNewsletterLambda)(plugin.functionName, {
      action: "confirm",
      token,
      ip: clientAddress(request.headers),
      userAgent: limited(request.headers.get("user-agent"), NEWSLETTER_USER_AGENT_CHARACTERS),
    });
    if (result.body.status !== "confirmed") return pageResponse(expiredPage(base), 410);
    const lists = Array.isArray(result.body.lists) ? (result.body.lists as Array<{ id?: unknown }>) : [];
    const ids = lists.flatMap((entry) => (typeof entry.id === "string" && LIST_ID.test(entry.id) ? [entry.id] : []));
    const target = publicSiteUrl(`/api/newsletter/confirm?done=1&l=${encodeURIComponent(ids.join(","))}`, request, environment);
    return NextResponse.redirect(target, { status: 303, headers: { ...NO_STORE, "referrer-policy": "no-referrer" } });
  } catch (error) {
    console.error(`Newsletter confirm failed (${error instanceof Error ? error.name : "error"}).`);
    return pageResponse(unavailablePage(base), 502);
  }
}
