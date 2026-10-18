"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { IssueCollection, IssueDetailPanel, IssueTypeFilter, issueTypeFromFilter } from "@kanbus/ui";
import "@kanbus/ui/styles/kanban.css";
import "./newsroom-newsprint-board.css";
import { canReadNewsroomBoard, contentItemBoardType, newsroomBoardConfig, projectNewsroomBoard, type NativeBoardIssue } from "../lib/newsroom-board";
import type { AssignmentRecord } from "../lib/category-repository";
import { getContentItemName, SITE_BRAND } from "../lib/site-brand";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { loadNewsroomAssignmentPage, loadNewsroomContentItemVersions, loadNewsroomPublishedContentItemVersions } from "./news-desk-taxonomy-client";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";
import { readLocalReaderSettings, subscribeReaderSettingsChanges } from "./reader-settings";

const STATIC_MOTION = { mode: "static" } as const;

async function loadEveryNewsroomAssignment() {
  const assignments: AssignmentRecord[] = [];
  let nextToken: string | null | undefined;
  do {
    const page = await loadNewsroomAssignmentPage({ limit: 100, nextToken });
    assignments.push(...page.items);
    nextToken = page.nextToken;
  } while (nextToken);
  return assignments;
}

/** Read-only shared board over authenticated CMS records; existing workspaces own every mutation. */
export function NewsroomBoardView() {
  const session = useOptionalNewsDeskClient();
  const allowed = canReadNewsroomBoard(session?.shell.phase);
  const theme = useResolvedPapyrusTheme();
  const [lowMotion, setLowMotion] = useState(false);
  const [issues, setIssues] = useState<NativeBoardIssue[]>([]);
  const [filter, setFilter] = useState(contentItemBoardType());
  const [view, setView] = useState<"board" | "list">("board");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    setLowMotion(readLocalReaderSettings().motion === "low");
    return subscribeReaderSettingsChanges(settings => setLowMotion(settings.motion === "low"));
  }, []);
  useEffect(() => {
    const request = ++generation.current;
    setIssues([]); setSelected(null); setError(null);
    if (!allowed) { setLoading(false); return; }
    setLoading(true);
    Promise.all([
      Promise.all([loadNewsroomContentItemVersions(), loadNewsroomPublishedContentItemVersions()]).then(([workingVersions, publishedVersions]) => [...workingVersions, ...publishedVersions]),
      loadEveryNewsroomAssignment(),
    ]).then(([contentItemVersions, assignments]) => {
      if (generation.current !== request) return;
      setIssues(projectNewsroomBoard({ contentItemVersions, assignments }));
    }).catch((reason: unknown) => {
      if (generation.current === request) setError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
    }).finally(() => { if (generation.current === request) { setLoading(false); } });
    return () => { generation.current = request + 1; };
  }, [allowed, revision]);
  const config = useMemo(() => newsroomBoardConfig(issues), [issues]);
  const issue = issues.find(item => item.id === selected);
  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab="board" appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle="Board">
    <div className="organizer-native-board papyrus-newsprint-board" data-color-mode={theme}>
      <div className="organizer-board-toolbar">
        <IssueTypeFilter config={config} value={filter} onChange={value => { setFilter(value); setSelected(null); }} name="Record type" />
        <div role="group" aria-label="Record presentation"><button type="button" aria-pressed={view === "board"} onClick={() => setView("board")}>Board</button><button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>List</button><button type="button" disabled={loading} onClick={() => setRevision(current => current + 1)}>Refresh records</button></div>
      </div>
      <p className="organizer-board-note">{`Each ${getContentItemName().singular.toLowerCase()} appears once, in the column for its stage. Open a record to use its existing editor or workflow controls.`}</p>
      {error && <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner>}
      <p role="status" className="organizer-board-note">{loading ? "Loading records…" : `${issues.length} records loaded.`}</p>
      <div className="organizer-board-body" data-detail-open={Boolean(issue)}>
        <IssueCollection issues={issues} config={config} query={{ type: issueTypeFromFilter(filter) }} view={view}
          motion={lowMotion ? STATIC_MOTION : undefined}
          columnStateKey={`papyrus.cms.columns.v1.${SITE_BRAND.id}`} initialScroll="start"
          selectedIssueId={selected} detailOpen={Boolean(issue)} onSelectIssue={item => setSelected(item.id)} ariaLabel="Newsroom records"
          emptyMessage={loading ? "Loading records…" : error ? "Records could not be loaded." : "No records in this selection."} />
        {issue && <IssueDetailPanel issue={issue} onClose={() => setSelected(null)} fields={[{ label: "CMS record ID", value: issue.nativeId }, { label: "Status", value: issue.nativeStatus }]}>
          <Link href={getNewsroomNavHref(issue.href)}>Open {issue.type}</Link>
        </IssueDetailPanel>}
      </div>
    </div>
  </NewsroomOpsShell>;
}
