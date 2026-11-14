import type { Metadata } from "next";
import { headers } from "next/headers";
import { NextRequest } from "next/server";
import { ConnectCliView } from "../../../../components/connect-cli-view";
import { cliConnectPlan } from "../../../../lib/cli-connect";
import { readCliLoginDocument } from "../../../../lib/cli-login-discovery";
import { SiteOriginNotConfiguredError } from "../../../../lib/site-origin";
import { getSiteBrand } from "../../../../lib/site-brand";

export const dynamic = "force-dynamic";

export function generateMetadata(): Metadata {
  return { title: `Connect the CLI or an agent · ${getSiteBrand().appTitle}` };
}

/** The same values `/.well-known/papyrus-cli.json` publishes, read on the server so the page cannot disagree with the file. */
export default async function ConnectCliPage() {
  const host = (await headers()).get("host") ?? "localhost";
  let plan = null;
  try {
    plan = cliConnectPlan(readCliLoginDocument(new NextRequest(`http://${host}/`)));
  } catch (error) {
    if (!(error instanceof SiteOriginNotConfiguredError)) throw error;
  }
  return <ConnectCliView plan={plan} />;
}
