"use client";

import { useEffect, useMemo, useState } from "react";
import { LoaderIcon } from "lucide-react";
import { SITE_BRAND } from "../lib/site-brand";
import { loadFeedSnapshot, type FeedSnapshot } from "../lib/reference-feed-cache";
import { partitionReferenceFeed, type ReferenceFeedTabKey } from "../lib/reference-feed-ranking";
import { selectCanonicalReferenceRecords } from "../lib/newsroom-references";
import { ReferenceFeed, ReferenceFeedSkeleton } from "./reference-feed";

/**
 * What the References page shows while the session and the first reads are still resolving: the real page header at once,
 * then this browser's last saved view (read only, answering switches on when the session is confirmed), or card skeletons
 * when there is none. Never a full-screen "checking" screen.
 */
export function ReferencesPageLoading() {
  const [snapshot, setSnapshot] = useState<FeedSnapshot | null>(null);
  const [checked, setChecked] = useState(false);
  const [tab, setTab] = useState<ReferenceFeedTabKey>("feed");
  const [note, setNote] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  useEffect(() => {
    setSnapshot(loadFeedSnapshot(SITE_BRAND.id));
    setChecked(true);
  }, []);
  const references = useMemo(() => selectCanonicalReferenceRecords(snapshot?.references ?? []), [snapshot]);
  const decisions = useMemo(() => new Map(snapshot?.decisions ?? []), [snapshot]);
  const previews = useMemo(() => new Map(snapshot?.previews ?? []), [snapshot]);
  const partition = useMemo(() => partitionReferenceFeed(references, decisions, { now }), [references, decisions, now]);
  const noVisitRated = useMemo(() => new Set<string>(), []);

  return (
    <div className="space-y-4" data-references-page-loading>
      <div className="space-y-1">
        <h2 className="text-2xl font-bold tracking-tight">References</h2>
        <p className="text-sm text-muted-foreground">A feed ranked by what you are most likely to accept.</p>
      </div>
      {note ? <p className="text-sm text-muted-foreground" role="status">{note}</p> : null}
      {checked && references.length ? (
        <ReferenceFeed
          disabledReason="Confirming your sign-in. You can answer in a moment."
          now={now}
          onOpen={() => setNote("Opening a reference is available in a moment, once your sign-in is confirmed.")}
          onRate={() => undefined}
          onTabChange={setTab}
          onVisitRated={() => undefined}
          partition={partition}
          previews={previews}
          stale
          tab={tab}
          visitRated={noVisitRated}
        />
      ) : (
        <>
          <p className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status"><LoaderIcon aria-hidden="true" className="size-3.5 animate-spin" />Loading your references</p>
          <ReferenceFeedSkeleton />
        </>
      )}
    </div>
  );
}
