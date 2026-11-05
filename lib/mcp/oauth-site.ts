import { CognitoJwtVerifier } from "aws-jwt-verify";
import { readAmplifyOutputsFile } from "../amplify-outputs-path";
import { fetchAuthSession } from "aws-amplify/auth/server";
import { NextRequest, NextResponse } from "next/server";
import { getAmplifyServerRuntime } from "../amplify-server-runtime";
import { resolveNewsroomChatIdentity } from "../newsroom-chat-identity";
import { loadProspectusSessionSealingSecret, signedInProspectusSession } from "../prospectus-session";
import { readerSubject } from "../reader-subject";
import { createOAuthHttp } from "./oauth-http";
import { invokeMcpOAuth, mcpOAuthConfig } from "./oauth-runtime";

/** Configuration is operator-provided; never use Host or client parameters as the issuer. */
export async function siteOAuth() {
  const config = mcpOAuthConfig();
  const secret = await loadProspectusSessionSealingSecret();
  if (!config || !secret) return null;
  let clients: Record<string, string[]>;
  try {
    const value: unknown = JSON.parse(process.env.PAPYRUS_MCP_OAUTH_CLIENTS ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.values(value).some(v => !Array.isArray(v) || v.some(x => typeof x !== "string"))) return null;
    clients = value as Record<string, string[]>;
  } catch { return null; }
  return createOAuthHttp({
    origin: config.origin, secret, clients,
    invoke: request => invokeMcpOAuth(request),
    identity: async request => {
      const nextRequest = new NextRequest(request);
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
      const reader = signedInProspectusSession(nextRequest, secret);
      const subject = readerSubject(reader);
      if (!reader || !subject || reader.accessTokenExpiresAt <= Math.floor(Date.now() / 1000)) return null;
      return { principal: { kind: "reader" as const, siteSubject: subject }, upstream_expiry: reader.accessTokenExpiresAt };
    },
  });
}

type HandlerName = "resource" | "metadata" | "authorize" | "consent" | "token" | "revoke";
export async function oauthRoute(name: HandlerName, request: Request) {
  try { const service = await siteOAuth(); return service ? service[name](request) : new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } }); }
  catch { return new Response(null, { status: 503, headers: { "Cache-Control": "no-store" } }); }
}
