import { handleSiteDocument } from "../../../lib/cli-site-document";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET() {
  return handleSiteDocument();
}
