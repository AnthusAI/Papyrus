import { CognitoJwtVerifier } from "aws-jwt-verify";
import type { JwksCache } from "aws-jwt-verify/jwk";
import type { NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";

export type NewsroomChatIdentity = { subject: string };
export type NewsroomChatIdentityResolver = (request: NextRequest) => Promise<NewsroomChatIdentity | null>;

export function newsroomChatIdentityResolver(
  auth: { user_pool_id: string; user_pool_client_id: string },
  jwksCache?: JwksCache,
): NewsroomChatIdentityResolver {
  const verifier = CognitoJwtVerifier.create({
    userPoolId: auth.user_pool_id,
    clientId: auth.user_pool_client_id,
    tokenUse: "access",
    groups: ["editor", "admin"],
  }, jwksCache ? { jwksCache } : undefined);
  return async (request) => {
    const token = request.headers.get("authorization")?.match(/^Bearer ([^\s]+)$/i)?.[1];
    if (!token) return null;
    try {
      const claims = await verifier.verify(token);
      return { subject: claims.sub };
    } catch {
      return null;
    }
  };
}

let configuredResolver: { key: string; resolve: NewsroomChatIdentityResolver } | undefined;

export async function resolveNewsroomChatIdentity(request: NextRequest): Promise<NewsroomChatIdentity | null> {
  const auth = readAmplifyOutputsFile()?.auth as { user_pool_id?: string; user_pool_client_id?: string } | undefined;
  if (!auth?.user_pool_id || !auth.user_pool_client_id) throw new Error("Newsroom identity configuration is unavailable");
  const key = `${auth.user_pool_id}:${auth.user_pool_client_id}`;
  if (configuredResolver?.key !== key) configuredResolver = { key, resolve: newsroomChatIdentityResolver({ user_pool_id: auth.user_pool_id, user_pool_client_id: auth.user_pool_client_id }) };
  return configuredResolver.resolve(request);
}
