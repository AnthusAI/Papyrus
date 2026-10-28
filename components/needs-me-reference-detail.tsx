"use client";

import { referenceDisplayTitle, referenceLineageId, formatReferenceListDate } from "../lib/newsroom-references";
import { referenceMetadataField } from "../lib/reference-display";
import { DEFAULT_TEASER_WORDS } from "../lib/reference-capture";
import { referenceReasonCode, normalizeReferenceCurationStatus } from "../lib/reference-policy";
import type { ReferenceRecord } from "../lib/category-repository";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import { DefaultOutcome, type DetailProps } from "./needs-me-bodies";
import { decidedChoiceOf } from "./needs-me-shared";
import { predictionFromDecision, ReviewCard, type CardPrediction } from "./reference-review-card";
import { ReferenceCapturePanel } from "./reference-capture-panel";
import { useReferenceCapture } from "./reference-capture-client";
import { ReferenceSourcePreview } from "./reference-source-preview";
import { ReferenceSuggestionProvenance } from "./reference-cyclotron-suggestion";
import { useReferencePreviewAttachments } from "./use-reference-preview-attachments";

function cardPrediction(item: NeedsMeEntry, predictionLoading: boolean): CardPrediction {
  if (item.payload.kind === "reference" && item.payload.decision) return predictionFromDecision(item.payload.decision);
  return predictionLoading ? { state: "loading" } : { state: "none" };
}

/** A Reference, or a Reference whose capture may be cut off: the References detail's own pieces, in the same order. */
export function ReferenceBody(props: DetailProps & { payload: Extract<NeedsMeEntry["payload"], { kind: "reference" }> }) {
  const { item, payload, ratings, disabledReason, attachments, captureTeaserLine = DEFAULT_TEASER_WORDS, onCorrectCapture, predictionLoading } = props;
  const reference: ReferenceRecord = payload.reference;
  const lineageId = referenceLineageId(reference);
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const previewAttachments = useReferencePreviewAttachments(reference, attachments);
  const capture = useReferenceCapture(reference, previewAttachments, captureTeaserLine, onCorrectCapture);
  const url = reference.sourceUri?.trim() && /^https?:\/\//i.test(reference.sourceUri.trim()) ? reference.sourceUri.trim() : null;
  const summary = referenceMetadataField(null, reference.metadata, "summary");
  const incomplete = item.type === "incomplete_capture";
  const capturePanel = <ReferenceCapturePanel capture={capture} startEditing={incomplete} />;
  return (
    <div className="space-y-4" data-reference-curation-status={status} data-news-desk-reference-detail={lineageId}>
      {incomplete ? (
        <div className="space-y-2" data-needs-me-capture-first>
          <p className="text-sm text-muted-foreground">The captured text looks cut off or missing. Paste the full text below and say whether the capture was complete, or rate the Reference as it is.</p>
          {capturePanel}
        </div>
      ) : null}
      <ReviewCard
        decided={decidedChoiceOf(item)}
        disabledReason={disabledReason}
        initialNote={status === "pending" ? "" : reference.curationStatusReason ?? ""}
        initialReason={referenceReasonCode(reference) ?? null}
        itemId={item.id}
        onDecide={async () => undefined}
        prediction={cardPrediction(item, predictionLoading)}
        ratings={ratings}
        summary={summary}
        title={referenceDisplayTitle(reference)}
        titleHref={url}
      >
        {payload.decision ? <div data-reference-relevance-decision={lineageId}><ReferenceSuggestionProvenance decision={payload.decision} /></div> : null}
      </ReviewCard>
      <DefaultOutcome item={item} />
      {incomplete ? null : capturePanel}
      <section aria-label="Source preview" className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">Source preview</h3>
        <ReferenceSourcePreview attachments={previewAttachments} sourceUri={reference.sourceUri} />
      </section>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Imported</dt>
          <dd className="mt-1 text-foreground">{formatReferenceListDate(reference)}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Media</dt>
          <dd className="mt-1 text-foreground">{reference.mediaType ?? "unknown"}</dd>
        </div>
      </dl>
    </div>
  );
}

