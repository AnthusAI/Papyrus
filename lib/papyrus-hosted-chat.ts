import { resolveNewsroomChatIdentity, type NewsroomChatIdentityResolver } from "./newsroom-chat-identity";
import { createHash } from "node:crypto";
import type { EmbeddedChatAppDependencies } from "chatticus/chat-server";
import type { NextRequest } from "next/server";
import { publicSiteOrigin } from "./site-origin-value";

const NO_STORE_HEADERS = { "cache-control": "no-store" };

export interface PapyrusChatScope {
  tenantId: string;
  editorId: string;
}

export interface PapyrusHostedChatOptions {
  resolveNewsroomIdentity?: NewsroomChatIdentityResolver;
  resolvePrivateDependencies?: () => Promise<EmbeddedChatAppDependencies | null>;
  privateChatEnabled?: boolean;
  environment?: Record<string, string | undefined>;
  nowInSeconds?: () => number;
}

/** A new namespace: never aliases Account-scoped or legacy transcripts. */
export function derivePapyrusChatScope(publicationNamespace: string, issuer: string, subject: string): PapyrusChatScope {
  const tenantHash = createHash("sha256").update(JSON.stringify(["newsroom-v1", publicationNamespace, issuer])).digest("hex");
  const editorHash = createHash("sha256").update(JSON.stringify(["newsroom-v1", publicationNamespace, issuer, subject])).digest("hex");
  return { tenantId: `papyrus-newsroom-v1-${tenantHash.slice(0, 40)}`, editorId: `papyrus-newsroom-editor-v1-${editorHash.slice(0, 40)}` };
}

/** Existing server storage resources bind the publication, independently of request hosts or claims. */
function publicationNamespace(environment: Record<string, string | undefined>, clientId: string): string | null {
  const bucket = environment.PAPYRUS_CHAT_SESSION_BUCKET?.trim();
  const table = environment.PAPYRUS_CHAT_MESSAGING_TABLE?.trim();
  return bucket && table ? JSON.stringify([bucket, table, clientId]) : null;
}

type ResolvedPapyrusPrincipal = {
  kind: "user";
  tenantId: string;
  userId: string;
  workerId: null;
  organizationStatus: "enabled";
  role: "member";
};

async function principalForRequest(
  request: NextRequest,
  options: PapyrusHostedChatOptions,
): Promise<{ principal: ResolvedPapyrusPrincipal | null; status: number; expiresAt?: number }> {
  let identity;
  try {
    identity = await (options.resolveNewsroomIdentity ?? resolveNewsroomChatIdentity)(request);
  } catch {
    return { principal: null, status: 503 };
  }
  const now = options.nowInSeconds?.() ?? Math.floor(Date.now() / 1000);
  if (!identity || !identity.subject || !identity.issuer || !identity.clientId || !Number.isFinite(identity.expiresAt) || identity.expiresAt <= now) return { principal: null, status: 401 };
  const namespace = publicationNamespace(options.environment ?? process.env, identity.clientId);
  if (!namespace) return { principal: null, status: 503 };
  const scope = derivePapyrusChatScope(namespace, identity.issuer, identity.subject);
  return {
    principal: { kind: "user", tenantId: scope.tenantId, userId: scope.editorId, workerId: null, organizationStatus: "enabled", role: "member" },
    status: 200,
    expiresAt: identity.expiresAt,
  };
}

function jsonFailure(status: number, error: string): Response {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { ...NO_STORE_HEADERS, "content-type": "application/json" },
  });
}

function supportedPath(path: readonly string[]): boolean {
  return (path.length === 1 && path[0] === "private-channel") ||
    (path.length === 3 && path[0] === "channels" && path[2] === "messages") ||
    (path.length === 3 && path[0] === "turns" && (path[2] === "events" || path[2] === "stream"));
}

function chatRequestPath(path: readonly string[]): string {
  return `/${path.map((part) => encodeURIComponent(part)).join("/")}`;
}

export async function handlePapyrusHostedChatRequest(
  request: NextRequest,
  path: readonly string[],
  options: PapyrusHostedChatOptions = {},
): Promise<Response> {
  if (!supportedPath(path) || path.some((part) => !part || part === "." || part === ".." || part.includes("/"))) {
    return jsonFailure(404, "chat_route_not_found");
  }
  if (request.method !== "GET" && request.method !== "POST") return jsonFailure(405, "method_not_allowed");
  const isMessageRoute = path[0] === "channels";
  const isPrivateChannelRoute = path[0] === "private-channel";
  if (isPrivateChannelRoute && request.method !== "POST") return jsonFailure(405, "method_not_allowed");
  if ((isMessageRoute && path[2] === "messages" && request.method === "POST") || (!isMessageRoute && !isPrivateChannelRoute && request.method !== "GET")) {
    if (!isMessageRoute && !isPrivateChannelRoute) return jsonFailure(405, "method_not_allowed");
  }
  if (isMessageRoute && request.method === "GET" && path[2] !== "messages") return jsonFailure(405, "method_not_allowed");
  if ((isMessageRoute || isPrivateChannelRoute) && request.method === "POST") {
    let origin: string;
    try {
      origin = publicSiteOrigin(request, options.environment ?? process.env);
    } catch {
      return jsonFailure(503, "chat_site_origin_unavailable");
    }
    if (request.headers.get("origin") !== origin) return jsonFailure(403, "same_origin_required");
  }

  const environment = options.environment ?? process.env;
  const privateChatEnabled = options.privateChatEnabled ?? environment.PAPYRUS_PRIVATE_CHAT_ENABLED === "true";
  if (!privateChatEnabled) return jsonFailure(404, "private_chat_disabled");

  const authorization = await principalForRequest(request, options);
  if (!authorization.principal) return jsonFailure(authorization.status, (authorization.status === 401 ? "sign_in_required" : authorization.status === 403 ? "chat_account_access_denied" : "chat_runtime_unavailable"));

  let dependencies: EmbeddedChatAppDependencies | null;
  try {
    if (options.resolvePrivateDependencies) {
      dependencies = await options.resolvePrivateDependencies();
    } else {
      const chatRuntime = await import("chatticus/chat-runtime");
      dependencies = chatRuntime.createSiteHostedChatDependencies(
        chatRuntime.siteHostedChatResourcesFromEnvironment(environment),
        chatRuntime.siteHostedChatClients(),
      ) as EmbeddedChatAppDependencies;
    }
  } catch {
    dependencies = null;
  }
  if (!dependencies) return jsonFailure(503, "private_chat_storage_unavailable");

  const headers = new Headers({ accept: request.headers.get("accept") ?? "application/json" });
  let body: string | undefined;
  if (request.method === "POST" && isMessageRoute) {
    const idempotencyKey = request.headers.get("idempotency-key")?.trim();
    const input = await request.json().catch(() => null) as Record<string, unknown> | null;
    const privateBotId = environment.PAPYRUS_CHAT_PRIVATE_BOT_ID?.trim();
    if (!idempotencyKey || typeof input?.body !== "string" || !input.body.trim()) {
      return jsonFailure(422, "message_body_and_idempotency_key_required");
    }
    if (!privateBotId) return jsonFailure(503, "private_chat_storage_unavailable");
    headers.set("content-type", "application/json");
    headers.set("idempotency-key", idempotencyKey);
    body = JSON.stringify({
      author_kind: "human",
      author_id: authorization.principal.userId,
      body: input.body,
      addressed_to_bot_id: privateBotId,
    });
  }

  const target = new URL(chatRequestPath(path) + new URL(request.url).search, request.url);
  const forwarded = new Request(target, { method: request.method, headers, ...(body === undefined ? {} : { body }) });
  let chatServer: typeof import("chatticus/chat-server");
  try {
    chatServer = await import("chatticus/chat-server");
  } catch {
    return jsonFailure(503, "private_chat_storage_unavailable");
  }
  const app = chatServer.createEmbeddedChatApp({
    ...dependencies,
    resolvePrincipal: async () => authorization.principal,
  });
  const response = await app.fetch(forwarded);
  if (path[0] !== "turns" || path[2] !== "stream" || !response.ok || !response.body) return response;
  const remaining = (authorization.expiresAt! - (options.nowInSeconds?.() ?? Date.now() / 1000)) * 1000;
  return expireChatStream(response, remaining);
}

/** End an established stream at JWT expiry; reconnect must pass current authorization again. */
export function expireChatStream(response: Response, remainingMilliseconds: number): Response {
  if (!response.body) return response;
  const reader = response.body.getReader();
  let closed = false;
  let timer: ReturnType<typeof setTimeout>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      timer = setTimeout(() => {
        if (closed) return;
        closed = true;
        controller.close();
        void reader.cancel().catch(() => {});
      }, Math.max(0, Math.min(remainingMilliseconds, 2_147_483_647)));
    },
    async pull(controller) {
      try {
        const next = await reader.read();
        if (closed) return;
        if (next.done) { closed = true; clearTimeout(timer); controller.close(); }
        else controller.enqueue(next.value);
      } catch (error) {
        if (!closed) { closed = true; clearTimeout(timer); controller.error(error); }
      }
    },
    async cancel(reason) { closed = true; clearTimeout(timer); await reader.cancel(reason); },
  });
  return new Response(body, { status: response.status, headers: response.headers });
}
