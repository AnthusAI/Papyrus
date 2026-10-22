import { isIP } from "node:net";
import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import { PROSPECTUS_SESSION_COOKIE, loadProspectusSessionSealingSecret } from "./prospectus-session";
import { signedInProspectusSession } from "./prospectus-sign-in-routes";
import { readerSubject } from "./reader-subject";
import { SiteOriginNotConfiguredError, publicSiteOrigin, siteOriginNotConfiguredResponse } from "./site-origin";

export const NEWSLETTER_FUNCTION_ENV = "PAPYRUS_NEWSLETTER_FUNCTION";
export const NEWSLETTER_SUBSCRIBE_MAXIMUM_BODY_BYTES = 8192;
export const NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES = 4096;
export const NEWSLETTER_USER_AGENT_CHARACTERS = 300;
export const NEWSLETTER_TOKEN = /^[A-Za-z0-9._-]{1,2048}$/;
const MAXIMUM_LISTS = 20;
const LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;

export type NewsletterEvent = { action: string } & Record<string, unknown>;
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

async function readBody(request: NextRequest, maximum: number, contentTypes: string[] | null): Promise<{ text: string } | { response: NextResponse }> {
  const contentType = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (contentTypes !== null && !contentTypes.includes(contentType)) return { response: failure(415, "unsupported_media_type", `Send ${(contentTypes ?? []).join(" or ")}.`) };
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

/**
 * Whether a state-changing request came from the site's own pages: its `Origin` is the public site origin or, when the browser
 * sent none, its `Referer` is on it. `Origin: null` (what a browser sends when the page said `Referrer-Policy: no-referrer`,
 * and what a sandboxed or cross-origin redirect chain produces) is never accepted.
 */
export function isSameSiteRequest(headers: Pick<Headers, "get">, siteOrigin: string): boolean {
  const origin = headers.get("origin");
  if (origin !== null) return origin === siteOrigin;
  const referer = headers.get("referer");
  if (!referer) return false;
  try {
    return new URL(referer).origin === siteOrigin;
  } catch {
    return false;
  }
}

/** The edge turns an origin answer of 403 or 404 into the site's 404 page, so failures here answer 400. */
const CROSS_SITE = { status: 400 } as const;

/** POST /api/newsletter/subscribe */
export async function handleNewsletterSubscribe(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundJson();
  const site = siteOriginOrResponse(request, environment);
  if ("response" in site) return site.response;
  if (!isSameSiteRequest(request.headers, site.origin)) return failure(CROSS_SITE.status, "origin_mismatch", "This request did not come from this site.");
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

/** The site's `urls.basePath` as a path with a leading slash ("/posts"), or "" for a site at the root. Anything unusable counts as no base path. */
function basePathOf(plugin: Enabled): string {
  const raw = plugin.settings.basePath;
  return typeof raw === "string" && /^[a-z0-9][a-z0-9_-]*(\/[a-z0-9][a-z0-9_-]*){0,2}$/.test(raw) ? `/${raw}` : "";
}

export type NewsletterPage = "confirm" | "confirmed" | "preferences" | "unsubscribe" | "unsubscribed" | "expired";

/**
 * People never land on /api. Every answer a person's browser can follow is a redirect to one of the plugin's projected pages,
 * `<base>/newsletter/<page>/` (the directory form, whatever the site's `urls.style`), which the site serves statically.
 */
function redirector(request: NextRequest, environment: Record<string, string | undefined>, plugin: Enabled): { origin: string; go: (page: NewsletterPage, query?: Record<string, string>, status?: 302 | 303) => NextResponse } | { response: NextResponse } {
  const site = siteOriginOrResponse(request, environment);
  if ("response" in site) return site;
  const base = basePathOf(plugin);
  return {
    origin: site.origin,
    go: (page, query = {}, status = 303) => {
      const search = new URLSearchParams(query).toString();
      return NextResponse.redirect(new URL(`${base}/newsletter/${page}/${search ? `?${search}` : ""}`, site.origin), {
        status,
        headers: { ...NO_STORE, "referrer-policy": "no-referrer" },
      });
    },
  };
}

function configuredLists(plugin: Enabled, ids: string[]): Array<{ id: string; name: string }> {
  const known = Array.isArray(plugin.settings.lists) ? (plugin.settings.lists as Array<{ id?: unknown; name?: unknown }>) : [];
  return ids.flatMap((id) => {
    const match = known.find((entry) => entry.id === id);
    return typeof match?.name === "string" ? [{ id, name: match.name }] : [];
  });
}

function call(options: NewsletterApiOptions, functionName: string, event: NewsletterEvent): Promise<NewsletterResult> {
  return (options.invoke ?? invokeNewsletterLambda)(functionName, event);
}

function textResponse(body: string, status: number): NextResponse {
  return new NextResponse(body, { status, headers: { ...NO_STORE, "content-type": "text/plain; charset=utf-8" } });
}

function manageTokenFrom(...values: Array<string | null>): string {
  const found = values.find((value) => value !== null && value !== "") ?? "";
  return NEWSLETTER_TOKEN.test(found) ? found : "";
}

function listParameter(value: string | null): string {
  return value !== null && LIST_ID.test(value) ? value : "";
}

function idsOf(lists: unknown): string[] {
  return (Array.isArray(lists) ? (lists as Array<{ id?: unknown }>) : []).flatMap((entry) => (typeof entry.id === "string" && LIST_ID.test(entry.id) ? [entry.id] : []));
}

/**
 * /api/newsletter/confirm. POST (form field `t`, from the confirm page) confirms and answers 303 to the confirmed page, or to the
 * expired page. GET is only for confirmation emails sent before the pages moved: it answers 302 to `<base>/newsletter/confirm/?token=`
 * and changes nothing.
 */
export async function handleNewsletterConfirm(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundPage();
  const to = redirector(request, environment, plugin);
  if ("response" in to) return to.response;
  if (request.method === "GET") {
    const token = manageTokenFrom(request.nextUrl.searchParams.get("t"));
    return token ? to.go("confirm", { token }, 302) : to.go("expired", {}, 302);
  }
  if (!isSameSiteRequest(request.headers, to.origin)) return to.go("expired");
  const body = await readBody(request, NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES, ["application/x-www-form-urlencoded"]);
  if ("response" in body) return body.response;
  const token = manageTokenFrom(new URLSearchParams(body.text).get("t"));
  if (!token || !plugin.functionName) return to.go("expired");
  try {
    const result = await call(options, plugin.functionName, {
      action: "confirm",
      token,
      ip: clientAddress(request.headers),
      userAgent: limited(request.headers.get("user-agent"), NEWSLETTER_USER_AGENT_CHARACTERS),
    });
    if (result.body.status !== "confirmed") return to.go("expired");
    const manage = typeof result.body.manageToken === "string" ? manageTokenFrom(result.body.manageToken) : "";
    return to.go("confirmed", { lists: idsOf(result.body.lists).join(","), ...(manage ? { token: manage } : {}) });
  } catch (error) {
    console.error(`Newsletter confirm failed (${error instanceof Error ? error.name : "error"}).`);
    return to.go("expired");
  }
}

/**
 * /api/newsletter/unsubscribe. RFC 8058 one-click: mail providers POST `List-Unsubscribe=One-Click` to the link in the message header
 * from their own servers, with no Origin, so there is no same-origin check; the answer is plain text, never a redirect. A POST from
 * the unsubscribe page carries `page=1` and gets a 303 to the unsubscribed page. GET (an old email's footer link) answers 302 to
 * `<base>/newsletter/unsubscribe/?token=&list=` and changes nothing.
 */
export async function handleNewsletterUnsubscribe(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundPage();
  const to = redirector(request, environment, plugin);
  if ("response" in to) return to.response;
  const query = request.nextUrl.searchParams;
  if (request.method === "GET") {
    const token = manageTokenFrom(query.get("t"));
    const listId = listParameter(query.get("l"));
    return token ? to.go("unsubscribe", { token, ...(listId ? { list: listId } : {}) }, 302) : to.go("expired", {}, 302);
  }
  const body = await readBody(request, NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES, null);
  if ("response" in body) return body.response;
  const form = new URLSearchParams(body.text);
  const oneClick = form.get("List-Unsubscribe") === "One-Click";
  const fromPage = form.get("page") === "1";
  if (!oneClick && !fromPage) return textResponse("Send List-Unsubscribe=One-Click.", 400);
  const token = manageTokenFrom(query.get("t"), form.get("t"));
  const listId = listParameter(query.get("l") ?? form.get("l"));
  const rejected = () => (fromPage ? to.go("expired") : textResponse("Invalid link.", 400));
  if (!token) return rejected();
  if (!plugin.functionName) return fromPage ? to.go("expired") : textResponse("Unavailable.", 503);
  try {
    const result = await call(options, plugin.functionName, { action: "unsubscribe", token, ...(listId ? { list: listId } : {}) });
    if (result.body.status !== "unsubscribed") return rejected();
    if (!fromPage) return textResponse("Unsubscribed.", 200);
    return to.go("unsubscribed", { lists: idsOf(result.body.lists).join(","), token });
  } catch (error) {
    console.error(`Newsletter unsubscribe failed (${error instanceof Error ? error.name : "error"}).`);
    return fromPage ? to.go("expired") : textResponse("Try again later.", 502);
  }
}

const PREFERENCE_MESSAGES = new Set(["saved", "unsubscribed"]);

/**
 * /api/newsletter/preferences. POST (same-origin form from the preferences page) saves, unsubscribes from everything, or deletes
 * after a confirm step, and answers 303 to the preferences page with `msg=saved|unsubscribed|deleted` or `step=delete`. GET (an old
 * email's manage link) answers 302 to `<base>/newsletter/preferences/?token=`.
 */
export async function handleNewsletterPreferences(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundPage();
  const to = redirector(request, environment, plugin);
  if ("response" in to) return to.response;
  if (request.method === "GET") {
    const token = manageTokenFrom(request.nextUrl.searchParams.get("t"));
    return token ? to.go("preferences", { token }, 302) : to.go("expired", {}, 302);
  }
  if (!isSameSiteRequest(request.headers, to.origin)) return to.go("expired");
  const body = await readBody(request, NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES, ["application/x-www-form-urlencoded"]);
  if ("response" in body) return body.response;
  const form = new URLSearchParams(body.text);
  const token = manageTokenFrom(form.get("t"));
  if (!token || !plugin.functionName) return to.go("expired");
  const action = form.get("action");
  if (action === "delete" && form.get("confirm") !== "1") return to.go("preferences", { token, step: "delete" });
  const operation =
    action === "save"
      ? { action: "update_preferences", token, lists: form.getAll("l").slice(0, MAXIMUM_LISTS).filter((id) => LIST_ID.test(id)) }
      : action === "unsubscribe_all"
        ? { action: "unsubscribe", token }
        : action === "delete"
          ? { action: "delete_subscriber", token }
          : null;
  if (!operation) return failure(400, "invalid_action", "Choose save, unsubscribe from everything, or delete.");
  try {
    const status = (await call(options, plugin.functionName, operation)).body.status;
    if (status === "deleted") return to.go("preferences", { msg: "deleted" });
    if (typeof status !== "string" || !PREFERENCE_MESSAGES.has(status)) return to.go("expired");
    return to.go("preferences", { token, msg: status });
  } catch (error) {
    console.error(`Newsletter preferences save failed (${error instanceof Error ? error.name : "error"}).`);
    return to.go("expired");
  }
}

/**
 * GET /api/newsletter/state: JSON for the projected pages' script, never HTML. `kind=confirm&t=` and `kind=preferences&t=` ask the
 * function (read only); `kind=lists&lists=a,b` names lists from the site's own settings. Failures answer 400 or 502 with a status
 * word, since the edge turns an origin 403 or 404 into the site's 404 page.
 */
export async function handleNewsletterState(request: NextRequest, options: NewsletterApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  const plugin = enabledPlugin(options, environment);
  if (!plugin) return notFoundJson();
  const params = request.nextUrl.searchParams;
  const kind = params.get("kind");
  const json = (status: number, body: Record<string, unknown>) => NextResponse.json(body, { status, headers: NO_STORE });
  if (kind === "lists") return json(200, { status: "ready", lists: configuredLists(plugin, listIds(params.get("lists") ?? "")) });
  if (kind !== "confirm" && kind !== "preferences") return json(400, { status: "invalid" });
  const token = manageTokenFrom(params.get("t"));
  if (!token) return json(400, { status: "invalid" });
  if (!plugin.functionName) return json(503, { status: "unavailable" });
  try {
    const result = await call(options, plugin.functionName, { action: kind === "confirm" ? "confirm_page_state" : "preferences_state", token });
    if (result.body.status !== "ready") return json(400, { status: "invalid" });
    const lists = Array.isArray(result.body.lists) ? (result.body.lists as Array<Record<string, unknown>>) : [];
    if (kind === "confirm") return json(200, { status: "ready", lists: lists.flatMap((entry) => (typeof entry.name === "string" ? [{ name: entry.name }] : [])) });
    return json(200, {
      status: "ready",
      email: typeof result.body.email === "string" ? result.body.email : "",
      lists: lists.map((entry) => ({ id: entry.id, name: entry.name, description: entry.description ?? "", subscribed: entry.subscribed === true })),
    });
  } catch (error) {
    console.error(`Newsletter state failed (${error instanceof Error ? error.name : "error"}).`);
    return json(502, { status: "unavailable" });
  }
}
