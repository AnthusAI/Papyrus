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
import { loadNewsroomAssignmentPage, loadNewsroomPublishedContentItemVersions } from "./news-desk-taxonomy-client";
import { usePagedContentItemVersions } from "./use-paged-content-item-versions";
import type { ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";
import { readLocalReaderSettings, subscribeReaderSettingsChanges } from "./reader-settings";

const STATIC_MOTION = { mode: "static" } as const;
const BOARD_REFRESH_INTERVAL_MILLISECONDS = 30_000;
const COLUMN_LOAD_MORE_DISTANCE_PIXELS = 240;

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
  const [assignmentBoardIssues, setAssignmentBoardIssues] = useState<NativeBoardIssue[]>([]);
  const [publishedVersions, setPublishedVersions] = useState<ContentItemVersionRecord[]>([]);
  const [assignments, setAssignments] = useState<AssignmentRecord[]>([]);
  const [view, setView] = useState<"board" | "list">("board");
  const [selected, setSelected] = useState<string | null>(null);
  const [supportingRecordsLoading, setSupportingRecordsLoading] = useState(false);
  const [supportingRecordsError, setSupportingRecordsError] = useState<string | null>(null);
  const generation = useRef(0);
  const boardBodyRef = useRef<HTMLDivElement | null>(null);
  const boardType = subject === "contentItem" ? contentItemBoardType() : ASSIGNMENT_BOARD_TYPE;
  const columnStateConfig = useMemo(() => subject === "contentItem" ? contentItemBoardConfig([]) : assignmentBoardConfig(assignmentBoardIssues), [assignmentBoardIssues, subject]);
  const columnState = useBoardColumnState({ config: columnStateConfig, storageKey: `papyrus.cms.columns.v1.${SITE_BRAND.id}.${subject}` });
  const openedCollapsedUntilOpenedStages = useMemo(() => subject !== "contentItem" ? [] : getContentItemStageDefinitions()
    .filter(definition => definition.collapsedUntilOpened && !columnState.collapsedColumns.has(`${boardType}/${definition.key}`))
    .map(definition => definition.key), [boardType, columnState.collapsedColumns, subject]);
  const pagedContentItems = usePagedContentItemVersions({ enabled: allowed && subject === "contentItem", openedCollapsedUntilOpenedStages });
  useEffect(() => {
    setLowMotion(readLocalReaderSettings().motion === "low");
    return subscribeReaderSettingsChanges(settings => setLowMotion(settings.motion === "low"));
  }, []);
  useEffect(() => {
    const request = ++generation.current;
    setAssignmentBoardIssues([]); setPublishedVersions([]); setAssignments([]); setSelected(null); setSupportingRecordsError(null);
    if (!allowed) { setSupportingRecordsLoading(false); return; }
    const loadSupportingRecords = () => subject === "contentItem"
      ? Promise.all([loadNewsroomPublishedContentItemVersions(), loadEveryNewsroomAssignment()]).then(([published, everyAssignment]) => {
        if (generation.current === request) { setPublishedVersions(published); setAssignments(everyAssignment); }
      })
      : loadEveryNewsroomAssignment().then(everyAssignment => {
        if (generation.current === request) setAssignmentBoardIssues(projectAssignmentBoard(everyAssignment));
      });
    const refresh = (initial: boolean) => {
      if (initial) setSupportingRecordsLoading(true);
      loadSupportingRecords().then(() => {
        if (generation.current === request) setSupportingRecordsError(null);
      }).catch((reason: unknown) => {
        if (generation.current === request && initial) setSupportingRecordsError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
      }).finally(() => { if (generation.current === request && initial) setSupportingRecordsLoading(false); });
    };
    refresh(true);
    const refreshWhenVisible = () => { if (document.visibilityState === "visible") refresh(false); };
    const interval = window.setInterval(refreshWhenVisible, BOARD_REFRESH_INTERVAL_MILLISECONDS);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => { generation.current = request + 1; window.clearInterval(interval); document.removeEventListener("visibilitychange", refreshWhenVisible); };
  }, [allowed, subject]);
  const issues = useMemo(() => subject === "contentItem"
    ? projectContentItemBoard({ contentItemVersions: [...pagedContentItems.versions, ...publishedVersions], assignments })
    : assignmentBoardIssues, [assignmentBoardIssues, assignments, pagedContentItems.versions, publishedVersions, subject]);
  const loading = supportingRecordsLoading || (subject === "contentItem" && pagedContentItems.loading);
  const error = supportingRecordsError ?? (subject === "contentItem" ? pagedContentItems.error : null);
  const config = useMemo(() => subject === "contentItem" ? contentItemBoardConfig(issues) : assignmentBoardConfig(issues), [issues, subject]);
  const columnStageFromElement = (element: Element | null) => element?.closest("[data-column-key]")?.getAttribute("data-column-key")?.slice(boardType.length + 1) ?? null;
  const loadMoreWhenColumnIsNearItsEnd = (columnScroll: HTMLElement) => {
    const distanceToEnd = columnScroll.scrollHeight - columnScroll.scrollTop - columnScroll.clientHeight;
    const stage = columnStageFromElement(columnScroll);
    if (stage && distanceToEnd < COLUMN_LOAD_MORE_DISTANCE_PIXELS) pagedContentItems.loadMoreForStage(stage);
  };
  const handleBoardScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (subject === "contentItem" && target.classList?.contains("kb-column-scroll")) loadMoreWhenColumnIsNearItsEnd(target);
  };
  useEffect(() => {
    if (subject !== "contentItem") return;
    boardBodyRef.current?.querySelectorAll<HTMLElement>(".kb-column-scroll").forEach(loadMoreWhenColumnIsNearItsEnd);
  });
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
      <div className="organizer-board-body" data-detail-open={Boolean(issue)} ref={boardBodyRef} onScrollCapture={handleBoardScroll}>
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
