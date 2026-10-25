import { createHash } from "node:crypto";
import type { EmbeddedChatAppDependencies } from "chatticus/chat-server";
import type { NextRequest } from "next/server";
import {
  ProspectusAccountsError,
  authorizeSignedInPersonForAccount,
} from "./prospectus-site-identity";
import {
  resolveProspectusSignInRuntime,
  signedInProspectusSession,
  type ProspectusSignInRuntime,
} from "./prospectus-session";
import { prospectusSiteProduct, publishingAccountsForSite } from "./prospectus-publication-access";
import { publicSiteOrigin } from "./site-origin-value";

const NO_STORE_HEADERS = { "cache-control": "no-store" };

export interface PapyrusChatScope {
  siteProduct: string;
  accountId: string;
  personId: string;
  tenantId: string;
  editorId: string;
}

export interface PapyrusHostedChatOptions {
  resolveRuntime?: (siteOrigin: string) => Promise<ProspectusSignInRuntime | null>;
  resolvePrivateDependencies?: () => Promise<EmbeddedChatAppDependencies | null>;
  privateChatEnabled?: boolean;
  siteProduct?: string | null;
  environment?: Record<string, string | undefined>;
  nowInSeconds?: () => number;
}

function siteAndAccountKey(siteProduct: string, accountId: string): string {
  return createHash("sha256").update(JSON.stringify([siteProduct, accountId])).digest("hex");
}

export function derivePapyrusChatScope(siteProduct: string, accountId: string, personId: string): PapyrusChatScope {
  const tenantHash = siteAndAccountKey(siteProduct, accountId);
  const editorHash = createHash("sha256").update(JSON.stringify([siteProduct, accountId, personId])).digest("hex");
  return {
    siteProduct,
    personId,
    accountId,
    tenantId: `papyrus-${tenantHash.slice(0, 40)}`,
    editorId: `papyrus-editor-${editorHash.slice(0, 40)}`,
  };
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
  operation: "console:read" | "console:write",
  options: PapyrusHostedChatOptions,
): Promise<{ principal: ResolvedPapyrusPrincipal | null; status: number }> {
  const environment = options.environment ?? process.env;
  const siteProduct = options.siteProduct !== undefined ? options.siteProduct : prospectusSiteProduct(environment);
  if (!siteProduct) return { principal: null, status: 503 };

  let runtime: ProspectusSignInRuntime | null;
  try {
    runtime = await (options.resolveRuntime ?? resolveProspectusSignInRuntime)(publicSiteOrigin(request, environment));
  } catch {
    return { principal: null, status: 503 };
  }
  if (!runtime) return { principal: null, status: 503 };

  const nowInSeconds = options.nowInSeconds?.() ?? Math.floor(Date.now() / 1000);
  const session = signedInProspectusSession(request, runtime.sealingSecret, nowInSeconds);
  if (!session || !session.selectedAccountId || !Number.isFinite(session.accessTokenExpiresAt) || session.accessTokenExpiresAt <= nowInSeconds) {
    return { principal: null, status: 401 };
  }

  try {
    const directory = await runtime.accounts.accountDirectory(session.accessToken);
    if (directory.person?.id !== session.personId) return { principal: null, status: 401 };
    if (!publishingAccountsForSite(directory.accounts, siteProduct).some((account) => account.accountId === session.selectedAccountId)) {
      return { principal: null, status: 403 };
    }
    const authorization = await authorizeSignedInPersonForAccount(
      runtime.accounts,
      session.accessToken,
      session.selectedAccountId,
      operation,
    );
    if (authorization.personId !== session.personId || authorization.accountId !== session.selectedAccountId || authorization.operation !== operation) {
      return { principal: null, status: 403 };
    }
    const scope = derivePapyrusChatScope(siteProduct, session.selectedAccountId, session.personId);
    return {
      principal: {
        kind: "user",
        tenantId: scope.tenantId,
        userId: scope.editorId,
        workerId: null,
        organizationStatus: "enabled",
        role: "member",
      },
      status: 200,
    };
  } catch (error) {
    if (error instanceof ProspectusAccountsError && (error.status === 401 || error.status === 403)) {
      return { principal: null, status: error.status };
    }
    return { principal: null, status: 503 };
  }
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

  const authorization = await principalForRequest(request, request.method === "POST" ? "console:write" : "console:read", options);
  if (!authorization.principal) return jsonFailure(authorization.status, authorization.status === 401 ? "sign_in_required" : authorization.status === 403 ? "chat_account_access_denied" : "chat_runtime_unavailable");

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
  return app.fetch(forwarded);
}
