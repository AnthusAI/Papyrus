"use client";

import { CheckIcon, SparklesIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { describeProbability, type EditorialFinding, type RewriteResult, type Span } from "../lib/editorial-checks";

export type RewriteTarget = { finding: EditorialFinding } | { selection: Span };
export type ApplyRewrite = (option: { span: Span; replacement: string; expected: string }, finding: EditorialFinding | null) => void;

export type FindingActions = {
  onSelect?: (finding: EditorialFinding) => void;
  onDismiss: (finding: EditorialFinding, reason: string) => void;
  onAccept: (finding: EditorialFinding) => void;
  onSuggest: (target: RewriteTarget, note: string | null) => Promise<RewriteResult>;
  onApply: ApplyRewrite;
};

type SuggestionState =
  | { state: "loading" }
  | { state: "ready"; result: RewriteResult }
  | { state: "error"; message: string };

/** Ask for rewrite options for a target and let the editor pick one. Shared by findings and selections. */
export function useRewriteOptions(actions: Pick<FindingActions, "onSuggest">) {
  const [suggestion, setSuggestion] = useState<SuggestionState | null>(null);
  const request = async (target: RewriteTarget, note: string | null) => {
    setSuggestion({ state: "loading" });
    try {
      setSuggestion({ state: "ready", result: await actions.onSuggest(target, note) });
    } catch (error) {
      setSuggestion({ state: "error", message: error instanceof Error ? error.message : "Could not get rewrite options." });
    }
  };
  return { suggestion, request, clear: () => setSuggestion(null) };
}

export function RewriteOptions({
  suggestion,
  finding,
  onApply,
}: {
  suggestion: SuggestionState | null;
  finding: EditorialFinding | null;
  onApply: ApplyRewrite;
}) {
  if (!suggestion) return null;
  if (suggestion.state === "loading") {
    return <p className="flex items-center gap-2 text-muted-foreground" data-editorial-rewrite-loading><Spinner /> Asking for rewrite options…</p>;
  }
  if (suggestion.state === "error") return <p className="text-destructive" role="alert">{suggestion.message}</p>;
  const { result } = suggestion;
  if (result.options.length === 0) return <p className="text-muted-foreground">No usable options this time. Try again or add a note.</p>;
  return (
    <div className="space-y-2" data-editorial-rewrite-options>
      <p className="text-xs text-muted-foreground" data-editorial-rewrite-target>Rewriting: “{result.target.excerpt}”</p>
      <ol className="space-y-2">
        {result.options.map((option, index) => (
          <li className="space-y-1 rounded-md bg-muted/40 p-2" data-editorial-rewrite-option={index} key={option.id}>
            <p>{option.replacement}</p>
            <p className="text-xs text-muted-foreground">{option.rationale}</p>
            {option.factVerificationRequired ? <p className="text-xs text-destructive">Changes a factual claim: verify before using.</p> : null}
            {option.unresolvedQuestions.length ? (
              <ul className="list-disc pl-4 text-xs text-muted-foreground">
                {option.unresolvedQuestions.map((question) => <li key={question}>{question}</li>)}
              </ul>
            ) : null}
            <Button
              data-editorial-use-option
              onClick={() => onApply({ span: option.span, replacement: option.replacement, expected: result.target.excerpt }, finding)}
              size="xs"
              type="button"
            >
              Use this
            </Button>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** One finding: what is wrong, how sure, and what the editor can do about it. */
export function EditorialFindingCard({
  finding,
  active = false,
  note,
  actions,
}: {
  finding: EditorialFinding;
  active?: boolean;
  note: string;
  actions: FindingActions;
}) {
  const [dismissing, setDismissing] = useState<string | null>(null);
  const rewrites = useRewriteOptions(actions);
  return (
    <div
      className="space-y-1 rounded-lg border border-border p-2 data-[active=true]:border-ring"
      data-active={active}
      data-editorial-finding-item={finding.id}
    >
      <button className="block w-full text-left" onClick={() => actions.onSelect?.(finding)} type="button">
        <span className="block">{finding.message}</span>
        {finding.excerpt ? <q className="block truncate text-muted-foreground">{finding.excerptText ?? finding.excerpt}</q> : null}
        <span className="text-xs text-muted-foreground">
          {finding.status === "review" ? "Needs your judgment · " : ""}
          {describeProbability(finding) ?? (finding.lane === "rules" ? "Rule" : "")}
        </span>
      </button>
      <div className="flex flex-wrap gap-1">
        {finding.replacement !== undefined ? (
          <Button
            data-editorial-use-replacement={finding.replacement}
            onClick={() => actions.onApply({ span: finding.span, replacement: finding.replacement ?? "", expected: finding.excerpt }, finding)}
            size="xs"
            type="button"
            variant="outline"
          >
            <CheckIcon aria-hidden="true" /> {finding.replacement ? `Use “${finding.replacement}”` : "Remove"}
          </Button>
        ) : null}
        {finding.excerpt ? (
          <Button data-editorial-suggest onClick={() => void rewrites.request({ finding }, note.trim() || null)} size="xs" type="button" variant="outline">
            <SparklesIcon aria-hidden="true" /> Suggest rewrites
          </Button>
        ) : null}
        {finding.status === "review" ? (
          <Button onClick={() => actions.onAccept(finding)} size="xs" type="button" variant="ghost">
            It&apos;s a problem
          </Button>
        ) : null}
        <Button data-editorial-dismiss onClick={() => setDismissing("")} size="xs" type="button" variant="ghost">
          <XIcon aria-hidden="true" /> Dismiss
        </Button>
      </div>
      {dismissing !== null ? (
        <form
          className="flex gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            actions.onDismiss(finding, dismissing);
            setDismissing(null);
          }}
        >
          <Input
            aria-label="Why dismiss?"
            autoFocus
            className="h-8"
            onChange={(event) => setDismissing(event.target.value)}
            placeholder="Why? (optional, helps tune this policy)"
            value={dismissing}
          />
          <Button data-editorial-confirm-dismiss size="xs" type="submit">Dismiss</Button>
        </form>
      ) : null}
      <RewriteOptions finding={finding} onApply={actions.onApply} suggestion={rewrites.suggestion} />
    </div>
  );
}
