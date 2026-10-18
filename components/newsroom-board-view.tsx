"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { IssueCollection, IssueDetailPanel, useBoardColumnState } from "@kanbus/ui";
import "@kanbus/ui/styles/kanban.css";
import "./newsroom-newsprint-board.css";
import { PlusIcon } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "../lib/utils";
import { newsroomHref } from "../lib/newsroom-base-path";
import {
  ASSIGNMENT_BOARD_TYPE,
  assignmentBoardConfig,
  canReadNewsroomBoard,
  contentItemBoardConfig,
  contentItemBoardType,
  projectAssignmentBoard,
  projectContentItemBoard,
  type NativeBoardIssue,
} from "../lib/newsroom-board";
import type { AssignmentRecord } from "../lib/category-repository";
import { getContentItemName, getContentItemStageDefinitions, SITE_BRAND } from "../lib/site-brand";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { loadNewsroomAssignmentPage, loadNewsroomContentItemVersions, loadNewsroomPublishedContentItemVersions } from "./news-desk-taxonomy-client";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";
import { readLocalReaderSettings, subscribeReaderSettingsChanges } from "./reader-settings";

const STATIC_MOTION = { mode: "static" } as const;
const BOARD_REFRESH_INTERVAL_MILLISECONDS = 30_000;

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

export type NewsroomBoardSubject = "contentItem" | "assignment";

/** Read-only board of one record kind over authenticated CMS records; existing workspaces own every mutation. */
export function NewsroomBoardView({ subject }: { subject: NewsroomBoardSubject }) {
  const session = useOptionalNewsDeskClient();
  const allowed = canReadNewsroomBoard(session?.shell.phase);
  const theme = useResolvedPapyrusTheme();
  const [lowMotion, setLowMotion] = useState(false);
  const [issues, setIssues] = useState<NativeBoardIssue[]>([]);
  const [view, setView] = useState<"board" | "list">("board");
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const openedCollapsedUntilOpenedStagesRef = useRef<string[]>([]);
  const refreshIssuesRef = useRef<((initial: boolean) => void) | null>(null);
  useEffect(() => {
    setLowMotion(readLocalReaderSettings().motion === "low");
    return subscribeReaderSettingsChanges(settings => setLowMotion(settings.motion === "low"));
  }, []);
  useEffect(() => {
    const request = ++generation.current;
    setIssues([]); setSelected(null); setError(null);
    if (!allowed) { setLoading(false); return; }
    const loadIssues = () => subject === "contentItem"
      ? Promise.all([
        Promise.all([loadNewsroomContentItemVersions({ includeCollapsedUntilOpenedStages: openedCollapsedUntilOpenedStagesRef.current }), loadNewsroomPublishedContentItemVersions()]).then(([workingVersions, publishedVersions]) => [...workingVersions, ...publishedVersions]),
        loadEveryNewsroomAssignment(),
      ]).then(([contentItemVersions, assignments]) => projectContentItemBoard({ contentItemVersions, assignments }))
      : loadEveryNewsroomAssignment().then(projectAssignmentBoard);
    const refresh = (initial: boolean) => {
      if (initial) setLoading(true);
      loadIssues().then(loadedIssues => {
        if (generation.current !== request) return;
        setIssues(loadedIssues);
        setError(null);
      }).catch((reason: unknown) => {
        if (generation.current === request && initial) setError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
      }).finally(() => { if (generation.current === request && initial) setLoading(false); });
    };
    refreshIssuesRef.current = refresh;
    refresh(true);
    const refreshWhenVisible = () => { if (document.visibilityState === "visible") refresh(false); };
    const interval = window.setInterval(refreshWhenVisible, BOARD_REFRESH_INTERVAL_MILLISECONDS);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => { generation.current = request + 1; window.clearInterval(interval); document.removeEventListener("visibilitychange", refreshWhenVisible); };
  }, [allowed, subject]);
  const config = useMemo(() => subject === "contentItem" ? contentItemBoardConfig(issues) : assignmentBoardConfig(issues), [issues, subject]);
  const boardType = subject === "contentItem" ? contentItemBoardType() : ASSIGNMENT_BOARD_TYPE;
  const columnState = useBoardColumnState({ config, storageKey: `papyrus.cms.columns.v1.${SITE_BRAND.id}.${subject}` });
  const openedCollapsedUntilOpenedStageKeys = useMemo(() => subject !== "contentItem" ? "" : getContentItemStageDefinitions()
    .filter(definition => definition.collapsedUntilOpened && !columnState.collapsedColumns.has(`${boardType}/${definition.key}`))
    .map(definition => definition.key).join(","), [boardType, columnState.collapsedColumns, subject]);
  useEffect(() => {
    openedCollapsedUntilOpenedStagesRef.current = openedCollapsedUntilOpenedStageKeys ? openedCollapsedUntilOpenedStageKeys.split(",") : [];
    if (openedCollapsedUntilOpenedStageKeys) refreshIssuesRef.current?.(false);
  }, [openedCollapsedUntilOpenedStageKeys]);
  const pageTitle = subject === "contentItem" ? getContentItemName().plural : "Assignments";
  const issue = issues.find(item => item.id === selected);
  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab={subject === "contentItem" ? "articles" : "assignments"} appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle={pageTitle}
    headerActions={<>
      <div role="group" aria-label="Record presentation" className="organizer-board-view-toggle"><button type="button" aria-pressed={view === "board"} onClick={() => setView("board")}>Board</button><button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>List</button></div>
      {subject === "contentItem" && (
        <Link className={cn(buttonVariants({ size: "sm" }))} data-newsroom-article-new href={getNewsroomNavHref(newsroomHref("articles", "new"))}>
          <PlusIcon aria-hidden="true" />
          {`New ${getContentItemName().singular.toLowerCase()}`}
        </Link>
      )}
    </>}>
    <div className="organizer-native-board papyrus-newsprint-board" data-color-mode={theme}>
      {error && <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner>}
      <p role="status" className="organizer-board-note">{loading ? "Loading records…" : `${issues.length} records loaded.`}</p>
      <div className="organizer-board-body" data-detail-open={Boolean(issue)}>
        <IssueCollection issues={issues} config={config} query={{ type: boardType }} view={view}
          motion={lowMotion ? STATIC_MOTION : undefined}
          collapsedColumns={columnState.collapsedColumns} onToggleCollapse={columnState.toggleColumn} initialScroll="start"
          selectedIssueId={selected} detailOpen={Boolean(issue)} onSelectIssue={item => setSelected(item.id)} ariaLabel={pageTitle}
          emptyMessage={loading ? "Loading records…" : error ? "Records could not be loaded." : "No records in this selection."} />
        {issue && <IssueDetailPanel issue={issue} onClose={() => setSelected(null)} fields={[{ label: "CMS record ID", value: issue.nativeId }, { label: "Status", value: issue.nativeStatus }]}>
          <Link href={getNewsroomNavHref(issue.href)}>Open {issue.type}</Link>
        </IssueDetailPanel>}
      </div>
    </div>
  </NewsroomOpsShell>;
}
