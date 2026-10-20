"use client";

import { SparklesIcon } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { groupByPolicy, laneNotice, visibleFindings, type EditorialCheckResult, type Span } from "../lib/editorial-checks";
import { EditorialFindingCard, RewriteOptions, useRewriteOptions, type FindingActions } from "./editorial-finding-card";

export type CheckStatus = { state: "idle" } | { state: "checking" } | { state: "error"; message: string };

type Props = FindingActions & {
  result: EditorialCheckResult | null;
  status: CheckStatus;
  dismissed: ReadonlySet<string>;
  activeFindingId: string | null;
  selection: Span;
  onCheck: () => void;
};

export const SEVERITY_LABEL = { error: "Must fix", warn: "Should fix", info: "Consider" } as const;
const SEVERITY_VARIANT = { error: "default", warn: "secondary", info: "muted" } as const;

export function EditorialFindingsPanel(props: Props) {
  const { result, status, dismissed, activeFindingId, selection } = props;
  const [note, setNote] = useState("");
  const selectionRewrites = useRewriteOptions(props);
  const findings = result ? visibleFindings(result.findings, dismissed) : [];
  const groups = groupByPolicy(findings);
  const notice = result ? laneNotice(result) : null;
  const hasSelection = selection.end > selection.start;

  return (
    <section aria-label="Editorial checks" className="space-y-3 rounded-xl border border-border bg-card p-3 text-sm" data-editorial-findings>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">Editorial checks</h3>
        {status.state === "checking" ? <Spinner aria-label="Checking" /> : null}
        <span className="text-muted-foreground" data-editorial-findings-count>
          {result ? `${findings.length} open` : "Not checked yet"}
        </span>
        <Button className="ml-auto" data-editorial-check-now disabled={status.state === "checking"} onClick={props.onCheck} size="xs" type="button" variant="outline">
          Check now
        </Button>
      </div>

      {status.state === "error" ? <p className="text-destructive" role="alert">{status.message}</p> : null}
      {notice ? <p className="text-muted-foreground" data-editorial-lane-notice>{notice}</p> : null}

      <div className="flex flex-wrap items-center gap-2" data-editorial-rewrite-tools>
        <Input
          aria-label="Note for rewrites"
          className="h-8 max-w-xs flex-1"
          onChange={(event) => setNote(event.target.value)}
          placeholder="Note for rewrites, e.g. shorter"
          value={note}
        />
        <Button
          disabled={!hasSelection}
          onClick={() => void selectionRewrites.request({ selection }, note.trim() || null)}
          size="xs"
          title={hasSelection ? "Get rewrite options for the selected text" : "Select text in the body first"}
          type="button"
          variant="outline"
        >
          <SparklesIcon aria-hidden="true" /> Rewrite selection
        </Button>
      </div>
      <RewriteOptions finding={null} onApply={props.onApply} suggestion={selectionRewrites.suggestion} />

      {result && findings.length === 0 ? <p className="text-muted-foreground">No open findings.</p> : null}
      {groups.map((group) => (
        <div className="space-y-2" data-editorial-policy={group.policyId} key={group.policyId}>
          <div className="flex items-center gap-2">
            <Badge variant={SEVERITY_VARIANT[group.severity]}>{SEVERITY_LABEL[group.severity]}</Badge>
            <strong>{group.policyId}</strong>
            <span className="text-muted-foreground">{group.findings.length}</span>
          </div>
          <ul className="space-y-2">
            {group.findings.map((finding) => (
              <li key={finding.id}>
                <EditorialFindingCard actions={props} active={finding.id === activeFindingId} finding={finding} note={note} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
