"use client";

import { useEffect, useMemo, useState } from "react";
import { LoaderIcon } from "lucide-react";
import { SITE_BRAND } from "../lib/site-brand";
import { loadFeedSnapshot, type FeedSnapshot } from "../lib/reference-feed-cache";
import { buildFeedItems, feedLeadId, visibleFeedItems } from "../lib/reference-feed-ranking";
import { selectCanonicalReferenceRecords } from "../lib/newsroom-references";
import { ReferenceFeed, ReferenceFeedSkeleton } from "./reference-feed";
import { useFeedPreferences } from "./use-feed-preferences";

/**
 * What the References page shows while the session and the first reads are still resolving: the real page header at once,
 * then this browser's last saved view (read only, answering switches on when the session is confirmed), or card skeletons
 * when there is none. Never a full-screen "checking" screen.
 */
export function ReferencesPageLoading() {
  const [snapshot, setSnapshot] = useState<FeedSnapshot | null>(null);
  const [checked, setChecked] = useState(false);
  const { sort, setSort, show, setShow } = useFeedPreferences();
  const [note, setNote] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  useEffect(() => {
    setSnapshot(loadFeedSnapshot(SITE_BRAND.id));
    setChecked(true);
  }, []);
  const references = useMemo(() => selectCanonicalReferenceRecords(snapshot?.references ?? []), [snapshot]);
  const decisions = useMemo(() => new Map(snapshot?.decisions ?? []), [snapshot]);
  const previews = useMemo(() => new Map(snapshot?.previews ?? []), [snapshot]);
  const noVisitRated = useMemo(() => new Set<string>(), []);
  const allItems = useMemo(() => buildFeedItems(references, decisions), [references, decisions]);
  const items = useMemo(() => visibleFeedItems(allItems, sort, show, noVisitRated), [allItems, sort, show, noVisitRated]);

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
          onShowChange={setShow}
          onSortChange={setSort}
          onVisitRated={() => undefined}
          items={items}
          leadId={feedLeadId(items)}
          ratedCount={allItems.filter((item) => item.rated).length}
          previews={previews}
          show={show}
          sort={sort}
          stale
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
