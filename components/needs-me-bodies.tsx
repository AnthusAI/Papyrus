"use client";

import { CheckIcon, CircleCheckIcon, CircleXIcon, ExternalLinkIcon, FileSearchIcon, Loader2Icon, LockIcon, MailIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { ReferenceAttachmentRecord } from "../lib/category-repository";
import { QUARANTINE_LABELS, type MonitoringEmailDetails } from "../lib/monitoring-overview";
import { sourceHost, requestCaption } from "../lib/notification-feed";
import { NEEDS_ME_TYPE_LABELS } from "../lib/needs-me-ranking";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import { answerWords, formatWhen, nextText, steeringText, subjectHref, subjectLabel } from "../lib/review-requests";
import { DecidedLine } from "./notification-cards";
import { SourceMark } from "./reference-feed";
import { RatingGrid } from "./review-rating-grid";
import type { RatingController } from "./use-reference-ratings";
import { FlagFooter, decidedChoiceOf } from "./needs-me-shared";

import type { CorrectCaptureAction } from "./reference-capture-client";
/** What the editor typed before deciding an item that is not a Reference: the optional why, and the one steering chip. */
export type DecisionExtras = { why: string; notThisKind: boolean };

const CHIP = "inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-full bg-[var(--feed-control)] px-2.5 text-xs font-medium text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-2 focus-visible:ring-ring";
const PILL_TOGGLE = "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-full px-3 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring";

export type DetailProps = {
  item: NeedsMeEntry;
  ratings: RatingController;
  extras: DecisionExtras;
  onExtras: (next: DecisionExtras) => void;
  disabledReason: string | null;
  attachments: ReferenceAttachmentRecord[];
  captureTeaserLine?: number;
  demo: boolean;
  predictionLoading: boolean;
  onCorrectCapture?: CorrectCaptureAction;
  loadEmail?: (receiptId: string) => Promise<MonitoringEmailDetails>;
};

export function Heading({ item }: { item: NeedsMeEntry }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs font-semibold" data-needs-me-detail-badges>
      <span className="inline-flex items-center rounded-full bg-[var(--feed-control)] px-2.5 py-1">{NEEDS_ME_TYPE_LABELS[item.type]}</span>
      {item.hardGate ? <span className="inline-flex items-center gap-1 rounded-full bg-[var(--feed-control)] px-2.5 py-1"><LockIcon aria-hidden="true" className="size-3.5" />Hard gate: waiting for you</span> : null}
      {item.decisionState !== "open" ? <span className="inline-flex items-center gap-1 rounded-full bg-[var(--feed-control)] px-2.5 py-1" data-needs-me-detail-state>{item.decisionState === "rejected" ? <CircleXIcon aria-hidden="true" className="size-3.5" /> : <CircleCheckIcon aria-hidden="true" className="size-3.5" />}{item.decisionState === "accepted" ? "Accepted" : item.decisionState === "rejected" ? "Rejected" : "Acknowledged"}</span> : null}
    </div>
  );
}

/** What was recorded when the item was decided, for the line under the buttons. */
function recordedAnswer(item: NeedsMeEntry): { why: string | null; notThisKind: boolean } {
  const { payload } = item;
  if (payload.kind === "draft") return { why: payload.item.decision?.why ?? null, notThisKind: Boolean(payload.item.decision?.notThisKind) };
  if (payload.kind === "request") return { why: payload.request.answer?.feedback ?? null, notThisKind: payload.request.answer?.steer === "not_this_kind" };
  if (payload.kind === "email") return { why: payload.summary.quarantine?.decision?.reason || null, notThisKind: false };
  return { why: null, notThisKind: false };
}

function chipLabel(item: NeedsMeEntry): string | null {
  return item.type === "draft" ? "Not this kind of story" : item.type === "stage_review" ? "Not this kind of thing" : null;
}

/** Accept / Reject for everything that is not a Reference: an optional why (read when you tap), one steering chip on Reject, then the shared grid. */
export function DecisionPanel({ item, ratings, extras, onExtras, disabledReason, lockedNote }: Pick<DetailProps, "item" | "ratings" | "extras" | "onExtras" | "disabledReason"> & { lockedNote?: ReactNode }) {
  const rating = ratings.get(item.id);
  const decided = decidedChoiceOf(item);
  const locked = item.decisionState !== "open";
  const busy = rating.feedback.phase === "saving";
  const flag = item.type === "flag";
  const chip = chipLabel(item);
  const recorded = recordedAnswer(item);

  // Desktop shortcuts: A accepts, R rejects. Never while typing, and never once decided.
  useEffect(() => {
    if (locked || flag) return undefined;
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (event.metaKey || event.ctrlKey || event.altKey || disabledReason) return;
      if (event.key === "a" || event.key === "A") ratings.choose(item.id, "accept");
      if (event.key === "r" || event.key === "R") ratings.choose(item.id, "reject");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <section aria-label="Your decision" className="space-y-3 rounded-[20px] bg-[var(--feed-footer)] p-3" data-needs-me-decision {...(locked ? {} : { "data-review-controls": "" })}>
      {locked ? (
        <>
          {item.decisionState === "acknowledged"
            ? <p className="flex items-center gap-1.5 text-sm font-medium" data-flag-acknowledged><CircleCheckIcon aria-hidden="true" className="size-4" />Acknowledged{recorded.why ? <span className="font-normal text-muted-foreground">: {recorded.why}</span> : null}</p>
            : <DecidedLine choice={decided ?? "accept"} notThisKind={recorded.notThisKind} why={recorded.why} />}
          {flag ? null : <RatingGrid answer={decided} disabled feedback={{ phase: "saved" }} onChoose={() => undefined} prediction={{ state: "none" }} showPrediction={false} size="large" surface="footer" />}
          {lockedNote ? <p className="text-xs text-muted-foreground" data-review-disabled-reason>{lockedNote}</p> : null}
        </>
      ) : (
        <>
          <textarea
            aria-label="Why? (optional)"
            className="block min-h-20 w-full resize-y rounded-[16px] bg-[var(--feed-control)] p-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
            data-needs-me-why
            onChange={(event) => onExtras({ ...extras, why: event.target.value })}
            placeholder={flag ? "Why? Optional. Tell the step what to do differently." : "Why? Optional. Your note teaches the AI."}
            readOnly={busy}
            value={extras.why}
          />
          {chip && !flag ? (
            <div className="flex flex-wrap items-center gap-2" data-review-reasons>
              <button
                aria-pressed={extras.notThisKind}
                className={cn(PILL_TOGGLE, extras.notThisKind ? "bg-[var(--primary)] font-semibold text-[var(--primary-foreground)]" : "bg-[var(--feed-control)]/60 text-muted-foreground hover:text-foreground")}
                data-review-reason="not_this_kind"
                onClick={() => onExtras({ ...extras, notThisKind: !extras.notThisKind })}
                type="button"
              >
                {extras.notThisKind ? <CheckIcon aria-hidden="true" className="size-3.5" /> : null}
                {chip}
              </button>
              <span className="text-xs text-muted-foreground">Optional. Counts if you reject.</span>
            </div>
          ) : null}
          {flag ? (
            <FlagFooter busy={busy} disabledReason={disabledReason} done={false} error={rating.feedback.phase === "error" ? rating.feedback.message ?? null : null} onAcknowledge={() => ratings.choose(item.id, "accept")} />
          ) : (
            <RatingGrid
              answer={rating.pending}
              disabled={Boolean(disabledReason)}
              disabledReason={disabledReason}
              feedback={rating.feedback}
              onChoose={(choice) => { if (!disabledReason) ratings.choose(item.id, choice); }}
              prediction={{ state: "none" }}
              showPrediction={false}
              size="large"
              surface="footer"
            />
          )}
        </>
      )}
    </section>
  );
}

export function DefaultOutcome({ item }: { item: NeedsMeEntry }) {
  return item.decisionState === "open" ? <p className="text-sm text-muted-foreground" data-needs-me-default-detail><strong className="font-semibold text-foreground">If you leave it:</strong> {item.defaultOutcome.replace(/^If you leave it,? ?/i, "").replace(/^./, (letter) => letter.toLowerCase())}</p> : null;
}

// --- one body per type -----------------------------------------------------------------------------------------------

export function DraftBody(props: DetailProps & { payload: Extract<NeedsMeEntry["payload"], { kind: "draft" }> }) {
  const { item, payload } = props;
  const { item: draft } = payload;
  const view = draft.view;
  if (!view) {
    return <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground" role="status"><Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Loading the draft…</p>;
  }
  return (
    <div className="space-y-4" data-draft-detail={draft.draftId}>
      <header className="space-y-1.5">
        <p className="text-xs font-medium text-muted-foreground">AI {view.kindLabel.toLowerCase()}{view.section ? ` · Section: ${view.section}` : ""}</p>
        <h2 className="break-words text-xl font-bold leading-tight tracking-tight text-foreground" data-draft-headline>{view.headline}</h2>
        {view.dek && !view.bodyText.startsWith(view.dek.replace(/\s*\[\d+\]$/, "").slice(0, 60)) ? <p className="break-words text-base text-muted-foreground" data-draft-dek>{view.dek}</p> : null}
      </header>
      {view.bodyText ? <div className="max-h-96 space-y-3 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-relaxed" data-draft-body tabIndex={0}>{view.bodyText}</div> : null}
      {view.evidence.length ? (
        <p aria-label="Evidence" className="flex items-start gap-1.5 break-words text-xs" data-draft-evidence>
          <FileSearchIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span><span className="font-semibold">Evidence:</span> {view.evidence.join(" ")}</span>
        </p>
      ) : null}
      {view.sources.length ? (
        <section aria-label="Citations" className="space-y-2">
          <h3 className="text-sm font-medium text-foreground">Citations</h3>
          <ul className="flex flex-wrap gap-1.5" data-draft-sources>
            {view.sources.map((source, index) => {
              const host = source.url ? sourceHost(source.url) : null;
              return (
                <li className="min-w-0 max-w-full" key={`${source.title}-${index}`}>
                  {source.url ? (
                    <a aria-label={`Source: ${source.title}${source.date ? ` (${source.date})` : ""}`} className={CHIP} data-draft-source href={source.url} rel="noreferrer" target="_blank" title={source.title}>
                      <SourceMark host={host} /><span className="truncate">{host ?? source.title}</span><ExternalLinkIcon aria-hidden="true" className="size-3 shrink-0 opacity-60" />
                    </a>
                  ) : <span className={CHIP} data-draft-source><span className="truncate">{source.title}</span></span>}
                </li>
              );
            })}
            {view.moreSources ? <li className="self-center text-xs text-muted-foreground">and {view.moreSources} more in the full draft</li> : null}
          </ul>
        </section>
      ) : null}
      <p className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span data-draft-caption>{requestCaption(draft.request)}</span>
        <Link className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline" data-draft-open href={view.href}>Open full draft<ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" /></Link>
      </p>
      <DefaultOutcome item={item} />
      <DecisionPanel {...props} lockedNote={<>To change it, <Link className="text-primary underline underline-offset-4" href={view.href}>open the draft in Proposals</Link>.</>} />
    </div>
  );
}

export function RequestBody(props: DetailProps & { payload: Extract<NeedsMeEntry["payload"], { kind: "request" }> }) {
  const { item, payload, demo } = props;
  const { request } = payload;
  const href = request.subject.type === "batch" ? null : subjectHref(request.subject, demo);
  const label = request.subject.type === "batch" ? null : subjectLabel(request.subject, payload.storyTitle ? { [request.subject.id]: payload.storyTitle } : {}, payload.storyDeleted ? new Set([request.subject.id]) : new Set());
  const steering = steeringText(request);
  return (
    <div className="space-y-4" data-review-mode={request.mode} data-review-request={request.id}>
      <header className="space-y-1.5">
        <h2 className="break-words text-xl font-bold leading-tight tracking-tight text-foreground">{request.reason}</h2>
        {request.ask ? <p className="break-words text-base text-muted-foreground" data-review-ask>The question: {request.ask}</p> : null}
      </header>
      {label ? <p className="break-words text-sm" data-review-about>About: {href ? <Link className="text-primary underline underline-offset-4" href={href}>{label}</Link> : label}</p> : null}
      {payload.excerpt ? (
        <section aria-label="The story" className="space-y-1.5" data-story-excerpt>
          <h3 className="text-sm font-medium text-foreground">The story{payload.storyTitle ? `: ${payload.storyTitle}` : ""}</h3>
          <div className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-2xl bg-[var(--feed-control)] p-3 text-sm leading-relaxed" tabIndex={0}>{payload.excerpt}</div>
        </section>
      ) : null}
      <p className="text-sm" data-review-next>{nextText(request)}</p>
      {steering ? <p className="text-sm" data-review-steering>{steering}</p> : null}
      <p className="text-xs text-muted-foreground" data-draft-caption>{requestCaption(request)}{request.state === "answered" && request.answer ? ` · answered ${formatWhen(request.answer.at)}` : ""}</p>
      <DecisionPanel {...props} lockedNote={request.answer ? `${answerWords(request.answer, request)} by ${request.answer.by} on ${formatWhen(request.answer.at)}.` : undefined} />
      {item.type === "flag" ? null : <DefaultOutcome item={item} />}
    </div>
  );
}

/** A held email is untrusted: its text is shown as text, its links as words, and nothing in it is opened or followed. */
export function EmailBody(props: DetailProps & { payload: Extract<NeedsMeEntry["payload"], { kind: "email" }> }) {
  const { item, payload, loadEmail } = props;
  const { summary } = payload;
  const [detail, setDetail] = useState<MonitoringEmailDetails | null>(null);
  useEffect(() => {
    if (!loadEmail) return undefined;
    let live = true;
    void loadEmail(summary.receiptId).then((next) => { if (live) setDetail(next); }, () => { if (live) setDetail({ state: "unavailable" }); });
    return () => { live = false; };
  }, [loadEmail, summary.receiptId]);
  const verdicts = Object.entries(summary.verdicts ?? {});
  return (
    <div className="space-y-4" data-email-submission-details={summary.receiptId}>
      <header className="space-y-1.5">
        <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><MailIcon aria-hidden="true" className="size-3.5" />{summary.quarantine ? QUARANTINE_LABELS[summary.quarantine.state] : "Email submission"}</p>
        <h2 className="break-words text-xl font-bold leading-tight tracking-tight text-foreground">{summary.subject?.trim() || "(no subject)"}</h2>
      </header>
      <p className="text-xs text-muted-foreground">Original content is shown as inert text. The sender and the message are untrusted; nothing in it is opened or run.</p>
      <dl className="grid gap-2 text-sm">
        <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Envelope sender</dt><dd className="break-words">{summary.envelopeSender || "unknown"}</dd></div>
        <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">From (unverified)</dt><dd className="break-words">{summary.headerFrom || "unknown"}</dd></div>
        {verdicts.length ? <div data-email-verdicts><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Checks</dt><dd className="flex flex-wrap gap-1.5">{verdicts.map(([name, value]) => <span className={CHIP} key={name}>{name.toUpperCase()} {value}</span>)}</dd></div> : null}
        {summary.warnings.length ? <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Warnings</dt><dd>{summary.warnings.join(", ")}</dd></div> : null}
      </dl>
      {detail && "submission" in detail ? (
        <>
          <section aria-label="Message text" className="space-y-1.5">
            <h3 className="text-sm font-medium text-foreground">Message text</h3>
            <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-2xl bg-[var(--feed-control)] p-3 text-sm" data-email-body tabIndex={0}>{detail.safeBodyText}</pre>
          </section>
          <section aria-label="Links in the message" className="space-y-1.5">
            <h3 className="text-sm font-medium text-foreground">Links in the message ({detail.candidateLinks.length})</h3>
            <p className="text-xs text-muted-foreground">Shown as text. They are not opened unless you accept the message.</p>
            <ul className="space-y-1 text-sm" data-email-links>
              {detail.candidateLinks.map((link, index) => <li className="break-all" key={`${link.url}-${index}`}>{link.title || "Source link"} <code className="text-xs">{link.url}</code></li>)}
            </ul>
          </section>
        </>
      ) : detail ? (
        <p className="text-sm text-muted-foreground" role="status">The message text could not be read right now.</p>
      ) : loadEmail ? (
        <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground" role="status"><Loader2Icon aria-hidden="true" className="size-4 animate-spin" />Reading the message…</p>
      ) : (
        <p className="text-sm text-muted-foreground">{summary.linkCount} candidate {summary.linkCount === 1 ? "link" : "links"} in the message.</p>
      )}
      <DefaultOutcome item={item} />
      <DecisionPanel {...props} lockedNote={summary.quarantine?.decision ? `${summary.quarantine.decision.action === "accept" ? "Accepted" : "Rejected"}${summary.quarantine.decision.at ? ` on ${formatWhen(summary.quarantine.decision.at)}` : ""}.` : "Decided here. Monitoring shows what became of it."} />
    </div>
  );
}

export function ConceptBody({ item }: { item: NeedsMeEntry }) {
  return (
    <div className="space-y-3" data-concept-detail>
      <h2 className="text-xl font-bold leading-tight tracking-tight text-foreground">{item.title}</h2>
      {item.dek ? <p className="text-base text-muted-foreground">{item.dek}</p> : null}
      <DefaultOutcome item={item} />
    </div>
  );
}

