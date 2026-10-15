"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { IssueCollection, IssueDetailPanel, IssueTypeFilter, issueTypeFromFilter } from "@kanbus/ui";
import "@kanbus/ui/styles/kanban.css";
import "./newsroom-newsprint-board.css";
import { canReadNewsroomBoard, newsroomBoardConfig, projectNewsroomBoard, type NativeBoardIssue } from "../lib/newsroom-board";
import { resolveArticlesBackend } from "../lib/newsroom-articles";
import { SITE_BRAND } from "../lib/site-brand";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { loadNewsroomAssignmentPage, loadNewsroomReferencePage } from "./news-desk-taxonomy-client";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";
import { readLocalReaderSettings, subscribeReaderSettingsChanges } from "./reader-settings";

const STATIC_MOTION = { mode: "static" } as const;

/** Read-only shared board over authenticated CMS records; existing workspaces own every mutation. */
export function NewsroomBoardView() {
  const session = useOptionalNewsDeskClient();
  const allowed = canReadNewsroomBoard(session?.shell.phase);
  const theme = useResolvedPapyrusTheme();
  const [lowMotion, setLowMotion] = useState(false);
  const [issues, setIssues] = useState<NativeBoardIssue[]>([]);
  const [filter, setFilter] = useState("all");
  const [view, setView] = useState<"board" | "list">("board");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tokens, setTokens] = useState<{ reference?: string | null; assignment?: string | null }>({});
  const generation = useRef(0);
  const busy = useRef(false);
  useEffect(() => {
    setLowMotion(readLocalReaderSettings().motion === "low");
    return subscribeReaderSettingsChanges(settings => setLowMotion(settings.motion === "low"));
  }, []);
  useEffect(() => {
    const request = ++generation.current;
    busy.current = false;
    setIssues([]); setSelected(null); setTokens({}); setError(null);
    if (!allowed) { setLoading(false); return; }
    setLoading(true); busy.current = true;
    Promise.all([
      resolveArticlesBackend(false).listRows(),
      loadNewsroomReferencePage({ limit: 50 }),
      loadNewsroomAssignmentPage({ limit: 50 }),
    ]).then(([articles, references, assignments]) => {
      if (generation.current !== request) return;
      setIssues(projectNewsroomBoard({ articles, references: references.items, assignments: assignments.items }));
      setTokens({ reference: references.nextToken, assignment: assignments.nextToken });
    }).catch((reason: unknown) => {
      if (generation.current === request) setError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
    }).finally(() => { if (generation.current === request) { setLoading(false); busy.current = false; } });
    return () => { generation.current = request + 1; };
  }, [allowed, revision]);
  async function loadMore(kind: "reference" | "assignment") {
    if (!allowed || busy.current || !tokens[kind]) return;
    const request = generation.current;
    busy.current = true; setLoading(true); setError(null);
    try {
      const added = kind === "reference"
        ? await loadNewsroomReferencePage({ limit: 50, nextToken: tokens.reference }).then(page => ({ issues: projectNewsroomBoard({ references: page.items }), token: page.nextToken }))
        : await loadNewsroomAssignmentPage({ limit: 50, nextToken: tokens.assignment }).then(page => ({ issues: projectNewsroomBoard({ assignments: page.items }), token: page.nextToken }));
      if (generation.current !== request) return;
      setIssues(current => [...new Map([...current, ...added.issues].map(issue => [issue.id, issue])).values()]);
      setTokens(current => ({ ...current, [kind]: added.token }));
    } catch (reason) {
      if (generation.current === request) setError(reason instanceof Error ? reason.message : "Could not load more records.");
    } finally { if (generation.current === request) { setLoading(false); busy.current = false; } }
  }
  const config = useMemo(() => newsroomBoardConfig(issues), [issues]);
  const issue = issues.find(item => item.id === selected);
  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab="work" appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle="Board">
    <div className="organizer-native-board papyrus-newsprint-board" data-color-mode={theme}>
      <div className="organizer-board-toolbar">
        <IssueTypeFilter config={config} value={filter} onChange={value => { setFilter(value); setSelected(null); }} name="Record type" />
        <div role="group" aria-label="Record presentation"><button type="button" aria-pressed={view === "board"} onClick={() => setView("board")}>Board</button><button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>List</button><button type="button" disabled={loading} onClick={() => setRevision(current => current + 1)}>Refresh records</button></div>
      </div>
      <p className="organizer-board-note">Native CMS records and statuses. Open a record to use its existing editor or workflow controls. Story linking is not configured.</p>
      {error && <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner>}
      <p role="status" className="organizer-board-note">{loading ? "Loading records…" : `${issues.length} records loaded. References and assignments load in pages.`}</p>
      <div className="organizer-board-body" data-detail-open={Boolean(issue)}>
        <IssueCollection issues={issues} config={config} query={{ type: issueTypeFromFilter(filter) }} view={view}
          motion={lowMotion ? STATIC_MOTION : undefined}
          columnStateKey={`papyrus.cms.columns.v1.${SITE_BRAND.id}`} initialScroll="start"
          selectedIssueId={selected} detailOpen={Boolean(issue)} onSelectIssue={item => setSelected(item.id)} ariaLabel="Newsroom records"
          emptyMessage={loading ? "Loading records…" : error ? "Records could not be loaded." : "No records in this selection."} />
        {issue && <IssueDetailPanel issue={issue} onClose={() => setSelected(null)} fields={[{ label: "CMS record ID", value: issue.nativeId }, { label: "Status", value: issue.nativeStatus }]}>
          <Link href={getNewsroomNavHref(issue.href)}>Open {issue.type} workspace</Link>
        </IssueDetailPanel>}
      </div>
      <div className="organizer-board-pages">{tokens.reference && <button disabled={loading} type="button" onClick={() => void loadMore("reference")}>Load more references</button>}{tokens.assignment && <button disabled={loading} type="button" onClick={() => void loadMore("assignment")}>Load more assignments</button>}</div>
    </div>
  </NewsroomOpsShell>;
}
