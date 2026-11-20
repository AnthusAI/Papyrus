import { oauthRoute } from "@/lib/mcp/oauth-site";
export const dynamic = "force-dynamic";
export const POST = (request: Request) => oauthRoute("revoke", request);
