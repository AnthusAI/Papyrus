import { oauthRoute } from "@/lib/mcp/oauth-site";
export const dynamic = "force-dynamic";
export const GET = (request: Request) => oauthRoute("consent", request);
export const POST = GET;
