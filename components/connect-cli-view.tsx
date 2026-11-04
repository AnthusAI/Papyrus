"use client";

import { SITE_BRAND } from "../lib/site-brand";
import type { CliConnectPlan } from "../lib/cli-connect";
import { ConnectCliBody } from "./connect-cli-body";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { articlesAccessBlocked } from "./newsroom-articles-view";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell } from "./newsroom-ops-shell";

export function ConnectCliView({ plan }: { plan: CliConnectPlan | null }) {
  const session = useOptionalNewsDeskClient();
  if (articlesAccessBlocked(session?.shell.phase)) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return (
    <NewsroomOpsShell activeTab="settings" appTitle={SITE_BRAND.appTitle} backHref="/" backLabel={SITE_BRAND.backToHomeLabel} pageTitle="Connect the CLI or an agent">
      <div className="w-full max-w-3xl">
        <ConnectCliBody plan={plan} />
      </div>
    </NewsroomOpsShell>
  );
}
