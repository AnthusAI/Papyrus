"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { IssueCollection, IssueDetailPanel, IssueTypeFilter, issueTypeFromFilter, useBoardColumnState } from "@kanbus/ui";
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
  deskBoardConfig,
  deskContainsAssignment,
  deskContainsContentItem,
  projectAssignmentBoard,
  projectContentItemBoard,
  type NativeBoardIssue,
} from "../lib/newsroom-board";
import type { AssignmentRecord, NewsroomSectionRecord } from "../lib/category-repository";
import { displayNewsroomSectionShortTitle } from "../lib/newsroom-sections";
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

export type NewsroomBoardSubject = "contentItem" | "assignment" | "desk";

/** Read-only board of one record kind over authenticated CMS records; existing workspaces own every mutation. */
export function NewsroomBoardView({ subject, deskId }: { subject: NewsroomBoardSubject; deskId?: string }) {
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
  const [typeFilter, setTypeFilter] = useState<string | null>("all");
  const showsContentItems = subject !== "assignment";
  const contentItemColumnKeyPrefix = `${contentItemBoardType()}/`;
  const boardType = subject === "assignment" ? ASSIGNMENT_BOARD_TYPE : contentItemBoardType();
  const deskAssignmentIssues = useMemo(() => subject === "desk" && deskId
    ? projectAssignmentBoard(assignments.filter(assignment => deskContainsAssignment(assignment, deskId))) : [], [assignments, deskId, subject]);
  const columnStateConfig = useMemo(() => subject === "contentItem" ? contentItemBoardConfig([])
    : subject === "desk" ? deskBoardConfig(deskAssignmentIssues)
    : assignmentBoardConfig(assignmentBoardIssues), [assignmentBoardIssues, deskAssignmentIssues, subject]);
  const columnState = useBoardColumnState({ config: columnStateConfig, storageKey: `papyrus.cms.columns.v1.${SITE_BRAND.id}.${subject}` });
  const openedCollapsedUntilOpenedStages = useMemo(() => !showsContentItems ? [] : getContentItemStageDefinitions()
    .filter(definition => definition.collapsedUntilOpened && !columnState.collapsedColumns.has(`${contentItemColumnKeyPrefix}${definition.key}`))
    .map(definition => definition.key), [contentItemColumnKeyPrefix, columnState.collapsedColumns, showsContentItems]);
  const pagedContentItems = usePagedContentItemVersions({ enabled: allowed && showsContentItems, openedCollapsedUntilOpenedStages });
  useEffect(() => {
    setLowMotion(readLocalReaderSettings().motion === "low");
    return subscribeReaderSettingsChanges(settings => setLowMotion(settings.motion === "low"));
  }, []);
  useEffect(() => {
    const request = ++generation.current;
    setAssignmentBoardIssues([]); setPublishedVersions([]); setAssignments([]); setSelected(null); setSupportingRecordsError(null);
    if (!allowed) { setSupportingRecordsLoading(false); return; }
    const loadSupportingRecords = () => subject !== "assignment"
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
  const issues = useMemo(() => {
    if (subject === "assignment") return assignmentBoardIssues;
    if (subject === "contentItem") return projectContentItemBoard({ contentItemVersions: [...pagedContentItems.versions, ...publishedVersions], assignments });
    const versionsOnDesk = [...pagedContentItems.versions, ...publishedVersions].filter(version => deskId && deskContainsContentItem(version, deskId));
    return [...projectContentItemBoard({ contentItemVersions: versionsOnDesk, assignments: assignments.filter(assignment => deskId && deskContainsAssignment(assignment, deskId)) }), ...deskAssignmentIssues];
  }, [assignmentBoardIssues, assignments, deskAssignmentIssues, deskId, pagedContentItems.versions, publishedVersions, subject]);
  const loading = supportingRecordsLoading || (showsContentItems && pagedContentItems.loading);
  const error = supportingRecordsError ?? (showsContentItems ? pagedContentItems.error : null);
  const config = useMemo(() => subject === "contentItem" ? contentItemBoardConfig(issues) : subject === "desk" ? deskBoardConfig(issues) : assignmentBoardConfig(issues), [issues, subject]);
  const columnStageFromElement = (element: Element | null) => {
    const columnKey = element?.closest("[data-column-key]")?.getAttribute("data-column-key");
    return columnKey?.startsWith(contentItemColumnKeyPrefix) ? columnKey.slice(contentItemColumnKeyPrefix.length) : null;
  };
  const loadMoreWhenColumnIsNearItsEnd = (columnScroll: HTMLElement) => {
    const distanceToEnd = columnScroll.scrollHeight - columnScroll.scrollTop - columnScroll.clientHeight;
    const stage = columnStageFromElement(columnScroll);
    if (stage && distanceToEnd < COLUMN_LOAD_MORE_DISTANCE_PIXELS) pagedContentItems.loadMoreForStage(stage);
  };
  const handleBoardScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (showsContentItems && target.classList?.contains("kb-column-scroll")) loadMoreWhenColumnIsNearItsEnd(target);
  };
  useEffect(() => {
    if (!showsContentItems) return;
    boardBodyRef.current?.querySelectorAll<HTMLElement>(".kb-column-scroll").forEach(loadMoreWhenColumnIsNearItsEnd);
  });
  const deskTitle = session?.shell.dashboard?.newsroomSections?.find(section => section.id === deskId)?.title ?? (deskId ? displayNewsroomSectionShortTitle({ id: deskId } as NewsroomSectionRecord) : "Desk");
  const pageTitle = subject === "contentItem" ? getContentItemName().plural : subject === "desk" ? deskTitle : "Assignments";
  const issue = issues.find(item => item.id === selected);
  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab={subject === "contentItem" ? "articles" : subject === "desk" ? "desks" : "assignments"} appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle={pageTitle}
    headerActions={<>
      <div role="group" aria-label="Record presentation" className="organizer-board-view-toggle"><button type="button" aria-pressed={view === "board"} onClick={() => setView("board")}>Board</button><button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>List</button></div>
      {showsContentItems && (
        <Link className={cn(buttonVariants({ size: "sm" }))} data-newsroom-article-new href={getNewsroomNavHref(newsroomHref("articles", "new"))}>
          <PlusIcon aria-hidden="true" />
          {`New ${getContentItemName().singular.toLowerCase()}`}
        </Link>
      )}
    </>}>
    <div className="organizer-native-board papyrus-newsprint-board" data-color-mode={theme}>
      {error && <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner>}
      <p role="status" className="organizer-board-note">{loading ? "Loading records…" : `${issues.length} records loaded.`}</p>
      {subject === "desk" && <IssueTypeFilter config={config} value={typeFilter} onChange={setTypeFilter} name="Record type" className="organizer-board-type-filter" />}
      <div className="organizer-board-body" data-detail-open={Boolean(issue)} ref={boardBodyRef} onScrollCapture={handleBoardScroll}>
        <IssueCollection issues={issues} config={config} query={{ type: subject === "desk" ? issueTypeFromFilter(typeFilter) : boardType }} view={view}
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
