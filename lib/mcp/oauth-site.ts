import { CognitoJwtVerifier } from "aws-jwt-verify";
import { readAmplifyOutputsFile } from "../amplify-outputs-path";
import { fetchAuthSession } from "aws-amplify/auth/server";
import { NextRequest, NextResponse } from "next/server";
import { getAmplifyServerRuntime } from "../amplify-server-runtime";
import { resolveNewsroomChatIdentity } from "../newsroom-chat-identity";
import { loadProspectusSessionSealingSecret, signedInProspectusSession } from "../prospectus-session";
import { handleProspectusSignInStart } from "../prospectus-sign-in-routes";
import { readerSubject } from "../reader-subject";
import { mcpOAuthClients } from "./oauth-clients";
import { createOAuthHttp, oauthMetadata } from "./oauth-http";
import { invokeMcpOAuth, mcpOAuthConfig } from "./oauth-runtime";

/** Preserve only the trusted fixed return path, never parameters supplied by the browser. */
export function mcpReaderSignInRequest(origin: string, request: Request): NextRequest {
  const url = new URL("/mcp/authorize", origin);
  url.searchParams.set("returnTo", "/mcp/authorize");
  return new NextRequest(url, { headers: request.headers });
}

/** Configuration is operator-provided; never use Host or client parameters as the issuer. */
export async function siteOAuth() {
  const config = mcpOAuthConfig();
  const clients = mcpOAuthClients();
  if (!config || !clients) return null;
  const secret = await loadProspectusSessionSealingSecret();
  if (!secret) throw new Error("Consent secret unavailable");
  return createOAuthHttp({
    origin: config.origin, secret, clients, readerSignInAvailable: process.env.PAPYRUS_SITE_ORIGIN === config.origin,
    readerSignIn: request => handleProspectusSignInStart(mcpReaderSignInRequest(config.origin, request)),
    invoke: request => invokeMcpOAuth(request),
    identity: async (request, kind) => {
      const nextRequest = new NextRequest(request);
      if (kind === "reader") {
        if (process.env.PAPYRUS_SITE_ORIGIN !== config.origin) return null;
        const reader = signedInProspectusSession(nextRequest, secret);
        const subject = readerSubject(reader);
        if (!reader || !subject || reader.accessTokenExpiresAt <= Math.floor(Date.now() / 1000)) return null;
        return { principal: { kind: "reader" as const, siteSubject: subject }, upstream_expiry: reader.accessTokenExpiresAt };
      }
      const response = new NextResponse();
      const { runWithAmplifyServerContext } = getAmplifyServerRuntime();
      const tokens = await runWithAmplifyServerContext({ nextServerContext: { request: nextRequest, response }, operation: async context => {
        try { const session = await fetchAuthSession(context); return { accessToken: session.tokens?.accessToken?.toString(), idToken: session.tokens?.idToken?.toString() }; } catch { return null; }
      } });
      if (tokens?.accessToken && tokens.idToken) {
        const auth = readAmplifyOutputsFile()?.auth as { user_pool_id?: string; user_pool_client_id?: string } | undefined;
        if (!auth?.user_pool_id || !auth.user_pool_client_id) throw new Error("Staff identity configuration unavailable");
        const headers = new Headers(); headers.set("authorization", `Bearer ${tokens.accessToken}`);
        const staff = await resolveNewsroomChatIdentity(new NextRequest(config.origin, { headers }));
        if (staff) {
          const access = await CognitoJwtVerifier.create({ userPoolId: auth.user_pool_id, clientId: auth.user_pool_client_id, tokenUse: "access" }).verify(tokens.accessToken);
          const id = await CognitoJwtVerifier.create({ userPoolId: auth.user_pool_id, clientId: auth.user_pool_client_id, tokenUse: "id" }).verify(tokens.idToken);
          if (access.sub !== id.sub || access.sub !== staff.subject || typeof id.auth_time !== "number" || access.auth_time !== id.auth_time) throw new Error("Tokens are not from one login");
          const expiry = Math.min(access.exp, id.exp, staff.expiresAt);
          return { principal: { kind: "staff" as const, subject: staff.subject, accessToken: tokens.accessToken, idToken: tokens.idToken, expiresAt: expiry }, upstream_expiry: expiry };
        }
      }
      return null;
    },
  });
}

type HandlerName = "resource" | "metadata" | "authorize" | "consent" | "token" | "revoke";
export async function oauthRoute(name: HandlerName, request: Request, dependencies: {
  config?: typeof mcpOAuthConfig;
  clients?: typeof mcpOAuthClients;
  service?: typeof siteOAuth;
} = {}) {
  try {
    const config = (dependencies.config ?? mcpOAuthConfig)();
    if (!config || !(dependencies.clients ?? mcpOAuthClients)()) return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
    if (name === "metadata" || name === "resource") return oauthMetadata(config.origin, name);
    const service = await (dependencies.service ?? siteOAuth)();
    if (!service) return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
    return service[name](request);
  } catch {
    if (name === "consent" || name === "authorize") return new Response("<!doctype html><html><head><title>Authorization unavailable</title></head><body><main><h1>Authorization unavailable</h1><p>Try again later or contact the site administrator, then restart authorization from your client.</p></main></body></html>", { status: 503, headers: { "Cache-Control": "no-store", "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'" } });
    return new Response(null, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
