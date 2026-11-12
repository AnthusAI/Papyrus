import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import {
  LIST_ID,
  MAXIMUM_LISTS,
  NEWSLETTER_CONFIRM_MAXIMUM_BODY_BYTES,
  NEWSLETTER_SUBSCRIBE_MAXIMUM_BODY_BYTES,
  NEWSLETTER_USER_AGENT_CHARACTERS,
  NO_STORE,
  clientAddress,
  failure,
  idsOf,
  isReadRequest,
  isSameSiteRequest,
  limited,
  listIds,
  listParameter,
  manageTokenFrom,
  readBody,
  siteOriginOrResponse,
  textResponse,
} from "./newsletter-api";

/**
 * The reader-facing routes of the `notifications` plugin (PPY-44721a). They follow `lib/newsletter-api.ts`: the same
 * same-origin rule, 400 and 303 rather than 403 and 404 (the edge rewrites those to the site's 404), and no network API:
 * each route invokes the site's own router function. A site without the plugin answers 404.
 */
export const NOTIFICATIONS_FUNCTION_ENV = "PAPYRUS_NOTIFICATIONS_FUNCTION";

export type NotificationsEvent = { action: string } & Record<string, unknown>;
export interface NotificationsResult {
  statusCode: number;
  body: Record<string, unknown>;
}
export type NotificationsInvoker = (functionName: string, event: NotificationsEvent) => Promise<NotificationsResult>;

export interface NotificationsApiOptions {
  environment?: Record<string, string | undefined>;
  invoke?: NotificationsInvoker;
  /** The parsed `amplify_outputs.json`; read from disk when absent. */
  outputs?: Record<string, unknown> | null;
}

export async function invokeNotificationsLambda(functionName: string, event: NotificationsEvent): Promise<NotificationsResult> {
  const { InvokeCommand, LambdaClient } = await import("@aws-sdk/client-lambda");
  const response = await new LambdaClient({}).send(
    new InvokeCommand({ FunctionName: functionName, InvocationType: "RequestResponse", Payload: Buffer.from(JSON.stringify(event)) }),
  );
  if (response.FunctionError || !response.Payload) throw new Error("notifications failed");
  const result = JSON.parse(Buffer.from(response.Payload).toString("utf8")) as Partial<NotificationsResult>;
  if (typeof result.statusCode !== "number" || typeof result.body !== "object" || result.body === null) {
    throw new Error("notifications returned an unexpected shape");
  }
  return { statusCode: result.statusCode, body: result.body as Record<string, unknown> };
}

type Enabled = { settings: Record<string, unknown>; functionName: string | null };

function enabledPlugin(options: NotificationsApiOptions, environment: Record<string, string | undefined>): Enabled | null {
  let outputs: Record<string, unknown> | null;
  try {
    outputs = options.outputs !== undefined ? options.outputs : readAmplifyOutputsFile();
  } catch {
    return null;
  }
  const custom = (outputs as { custom?: { papyrusPlugins?: Record<string, unknown>; notifications?: { actionsFunction?: unknown } } } | null)?.custom;
  const settings = custom?.papyrusPlugins?.notifications;
  if (typeof settings !== "object" || settings === null) return null;
  const fromEnvironment = (environment[NOTIFICATIONS_FUNCTION_ENV] ?? "").trim();
  const fromOutputs = custom?.notifications?.actionsFunction;
  const functionName = fromEnvironment || (typeof fromOutputs === "string" && fromOutputs.trim() ? fromOutputs.trim() : null);
  return { settings: settings as Record<string, unknown>, functionName };
}

const notFoundJson = () => failure(404, "not_found", "Not found.");
const notFoundPage = () => textResponse("Not found", 404);

function basePathOf(plugin: Enabled): string {
  const raw = plugin.settings.basePath;
  return typeof raw === "string" && /^[a-z0-9][a-z0-9_-]*(\/[a-z0-9][a-z0-9_-]*){0,2}$/.test(raw) ? `/${raw}` : "";
}

export type NotificationsPage = "confirm" | "confirmed" | "preferences" | "unsubscribe" | "unsubscribed" | "expired";

/** People never land on /api: every answer a browser can follow is a redirect to `<base>/notifications/<page>/`. */
function redirector(request: NextRequest, environment: Record<string, string | undefined>, plugin: Enabled) {
  const site = siteOriginOrResponse(request, environment);
  if ("response" in site) return site;
  const base = basePathOf(plugin);
  return {
    origin: site.origin,
    go: (page: NotificationsPage, query: Record<string, string> = {}, status: 302 | 303 = 303) => {
      const search = new URLSearchParams(query).toString();
      return NextResponse.redirect(new URL(`${base}/notifications/${page}/${search ? `?${search}` : ""}`, site.origin), {
        status,
        headers: { ...NO_STORE, "referrer-policy": "no-referrer" },
      });
    },
  };
}

const call = (options: NotificationsApiOptions, functionName: string, event: NotificationsEvent) =>
  (options.invoke ?? invokeNotificationsLambda)(functionName, event);

function context(request: NextRequest, options: NotificationsApiOptions) {
  const environment = options.environment ?? process.env;
  return { environment, plugin: enabledPlugin(options, environment) };
}

/** POST /api/notifications/subscribe */
export async function handleNotificationsSubscribe(request: NextRequest, options: NotificationsApiOptions = {}): Promise<NextResponse> {
  const { environment, plugin } = context(request, options);
  if (!plugin) return notFoundJson();
  const site = siteOriginOrResponse(request, environment);
  if ("response" in site) return site.response;
  if (!isSameSiteRequest(request.headers, site.origin)) return failure(400, "origin_mismatch", "This request did not come from this site.");
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
  if (!plugin.functionName) return failure(503, "notifications_unavailable", "Notification signup is not available right now.");
  const event: NotificationsEvent = {
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
  };
  try {
    const result = await call(options, plugin.functionName, event);
    const status = typeof result.body.status === "string" ? result.body.status : "error";
    return NextResponse.json({ status }, { status: result.statusCode, headers: NO_STORE });
  } catch (error) {
    console.error(`Notifications subscribe failed (${error instanceof Error ? error.name : "error"}).`);
    return failure(502, "notifications_unavailable", "Notification signup could not be reached.");
  }
}

/** /api/notifications/confirm. POST (form field `t`, same origin) confirms and answers 303; GET only redirects to the confirm page. */
export async function handleNotificationsConfirm(request: NextRequest, options: NotificationsApiOptions = {}): Promise<NextResponse> {
  const { environment, plugin } = context(request, options);
  if (!plugin) return notFoundPage();
  const to = redirector(request, environment, plugin);
  if ("response" in to) return to.response;
  if (isReadRequest(request)) {
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
    console.error(`Notifications confirm failed (${error instanceof Error ? error.name : "error"}).`);
    return to.go("expired");
  }
}

/** /api/notifications/unsubscribe. RFC 8058 one-click from mail providers (no Origin, plain text answer) or the page's POST (303). */
export async function handleNotificationsUnsubscribe(request: NextRequest, options: NotificationsApiOptions = {}): Promise<NextResponse> {
  const { environment, plugin } = context(request, options);
  if (!plugin) return notFoundPage();
  const to = redirector(request, environment, plugin);
  if ("response" in to) return to.response;
  const query = request.nextUrl.searchParams;
  if (isReadRequest(request)) {
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
    console.error(`Notifications unsubscribe failed (${error instanceof Error ? error.name : "error"}).`);
    return fromPage ? to.go("expired") : textResponse("Try again later.", 502);
  }
}

const PREFERENCE_MESSAGES = new Set(["saved", "unsubscribed"]);

/** /api/notifications/preferences. POST (same-origin form) saves, unsubscribes from everything, or deletes after a confirm step; GET redirects. */
export async function handleNotificationsPreferences(request: NextRequest, options: NotificationsApiOptions = {}): Promise<NextResponse> {
  const { environment, plugin } = context(request, options);
  if (!plugin) return notFoundPage();
  const to = redirector(request, environment, plugin);
  if ("response" in to) return to.response;
  if (isReadRequest(request)) {
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
    console.error(`Notifications preferences save failed (${error instanceof Error ? error.name : "error"}).`);
    return to.go("expired");
  }
}

function configuredLists(plugin: Enabled, ids: string[]): Array<{ id: string; name: string }> {
  const known = Array.isArray(plugin.settings.lists) ? (plugin.settings.lists as Array<{ id?: unknown; name?: unknown }>) : [];
  return ids.flatMap((id) => {
    const match = known.find((entry) => entry.id === id);
    return typeof match?.name === "string" ? [{ id, name: match.name }] : [];
  });
}

function offeredLists(plugin: Enabled): Array<{ id: string; name: string; description: string }> {
  const known = Array.isArray(plugin.settings.lists) ? (plugin.settings.lists as Array<{ id?: unknown; name?: unknown; description?: unknown }>) : [];
  return known.flatMap((entry) =>
    typeof entry.id === "string" && typeof entry.name === "string"
      ? [{ id: entry.id, name: entry.name, description: typeof entry.description === "string" ? entry.description : "" }]
      : [],
  );
}

/** GET /api/notifications/state: JSON for the pages' script (`kind=offered` lists the site's lists and its consent wording for the subscribe form). Failures answer 400, 502 or 503 with a status word, never 403 or 404. */
export async function handleNotificationsState(request: NextRequest, options: NotificationsApiOptions = {}): Promise<NextResponse> {
  const { plugin } = context(request, options);
  if (!plugin) return notFoundJson();
  const params = request.nextUrl.searchParams;
  const kind = params.get("kind");
  const json = (status: number, body: Record<string, unknown>) => NextResponse.json(body, { status, headers: NO_STORE });
  if (kind === "lists") return json(200, { status: "ready", lists: configuredLists(plugin, listIds(params.get("lists") ?? "")) });
  // Every list the site offers, for the subscribe form. Public settings only; nothing about any reader.
  if (kind === "offered") {
    // The form shows exactly this sentence and posts it back; the function refuses any other wording (consent evidence).
    const consent = typeof plugin.settings.consent === "string" ? plugin.settings.consent : "";
    return json(200, { status: "ready", lists: offeredLists(plugin), consent });
  }
  if (kind !== "confirm" && kind !== "preferences") return json(400, { status: "invalid" });
  const token = manageTokenFrom(params.get("t"));
  if (!token) return json(400, { status: "invalid" });
  if (!plugin.functionName) return json(503, { status: "unavailable" });
  try {
    const result = await call(options, plugin.functionName, { action: kind === "confirm" ? "confirm_page_state" : "preferences_state", token });
    if (result.body.status === "unavailable") return json(503, { status: "unavailable" });
    if (result.body.status !== "ready") return json(400, { status: "invalid" });
    const lists = Array.isArray(result.body.lists) ? (result.body.lists as Array<Record<string, unknown>>) : [];
    if (kind === "confirm") return json(200, { status: "ready", lists: lists.flatMap((entry) => (typeof entry.name === "string" ? [{ name: entry.name }] : [])) });
    return json(200, {
      status: "ready",
      email: typeof result.body.email === "string" ? result.body.email : "",
      lists: lists.map((entry) => ({ id: entry.id, name: entry.name, description: entry.description ?? "", subscribed: entry.subscribed === true })),
    });
  } catch (error) {
    console.error(`Notifications state failed (${error instanceof Error ? error.name : "error"}).`);
    return json(502, { status: "unavailable" });
  }
}
