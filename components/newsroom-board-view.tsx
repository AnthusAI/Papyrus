"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { IssueCollection, IssueDetailPanel, IssueIdFormatProvider, IssueTypeFilter, issueTypeFromFilter, useBoardColumnState } from "@kanbus/ui";
import "./newsroom-theme";
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
  formatNativeIssueId,
  projectAssignmentBoard,
  projectContentItemBoard,
  type NativeBoardIssue,
} from "../lib/newsroom-board";
import type { AssignmentRecord, NewsroomSectionRecord } from "../lib/category-repository";
import { displayNewsroomSectionShortTitle, newsroomDeskOptions } from "../lib/newsroom-sections";
import { getContentItemName, getContentItemStageDefinitions, SITE_BRAND } from "../lib/site-brand";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { loadNewsroomAssignmentPage, saveNewsroomAssignmentDesk } from "./news-desk-taxonomy-client";
import { usePagedContentItemVersions } from "./use-paged-content-item-versions";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { NewsroomBoardSkeleton } from "./newsroom-board-skeleton";
import { NewsroomBoardHeaderActions } from "./newsroom-board-header-actions";
import { NewsroomArticleEditor } from "./newsroom-article-editor";
import { resolveArticlesBackend } from "../lib/newsroom-articles";
import { StoryCardStars, useStoryCardSlots } from "./story-board-stars";
import { StoryCardChecklist, useStoryChecklistSlots } from "./story-checklist-card";
import { StoryChecklistPanel } from "./story-checklist-panel";
import { useStoryStars } from "./use-story-stars";
import { NewsroomAssignmentDetail } from "./newsroom-assignment-detail";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { startBoardRefresh } from "../lib/board-refresh";
import { readLocalReaderSettings, subscribeReaderSettingsChanges } from "./reader-settings";

/** A board with a story or assignment open lives at `?open=<id>`, distinct from the standalone page for that record. */
const SELECTED_ISSUE_PARAMETER = "open";
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

export type NewsroomBoardSubject = "contentItem" | "assignment" | "desk";

/** Read-only board of one record kind over authenticated CMS records; existing workspaces own every mutation. */
export function NewsroomBoardView({ subject, deskId }: { subject: NewsroomBoardSubject; deskId?: string }) {
  const session = useOptionalNewsDeskClient();
  const allowed = canReadNewsroomBoard(session?.shell.phase);
  const [lowMotion, setLowMotion] = useState(false);
  const [assignmentBoardIssues, setAssignmentBoardIssues] = useState<NativeBoardIssue[]>([]);
  const [assignments, setAssignments] = useState<AssignmentRecord[]>([]);
  const [view, setView] = useState<"board" | "list">("board");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selected = searchParams.get(SELECTED_ISSUE_PARAMETER);
  const setSelected = useCallback((issueId: string | null) => {
    const next = new URLSearchParams(searchParams.toString());
    if (issueId) next.set(SELECTED_ISSUE_PARAMETER, issueId); else next.delete(SELECTED_ISSUE_PARAMETER);
    const query = next.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);
  const [supportingRecordsLoading, setSupportingRecordsLoading] = useState(false);
  const [supportingRecordsError, setSupportingRecordsError] = useState<string | null>(null);
  const generation = useRef(0);
  const boardBodyRef = useRef<HTMLDivElement | null>(null);
  const articlesBackend = useMemo(() => resolveArticlesBackend(isLocalPreviewEnabled()), []);
  const storyStars = useStoryStars((itemId, stars) => articlesBackend.actions.setItemStars(itemId, stars));
  const storyCardSlots = useStoryCardSlots(boardBodyRef, subject !== "assignment");
  const storyChecklistSlots = useStoryChecklistSlots(boardBodyRef, subject !== "assignment");
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
  const refreshSupportingRecordsRef = useRef<() => Promise<void>>(async () => undefined);
  const pagedRefreshRef = useRef(pagedContentItems.refresh);
  pagedRefreshRef.current = pagedContentItems.refresh;
  const refreshBoardNowRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    const request = ++generation.current;
    setAssignmentBoardIssues([]); setAssignments([]); setSupportingRecordsError(null);
    if (!allowed) { setSupportingRecordsLoading(false); return; }
    // Assignments have no index that answers "changed since", so they are still read whole (follow-up: a feed + updatedAt index).
    const loadSupportingRecords = () => loadEveryNewsroomAssignment().then(everyAssignment => {
      if (generation.current !== request) return;
      setAssignments(everyAssignment);
      if (subject === "assignment") setAssignmentBoardIssues(projectAssignmentBoard(everyAssignment));
    });
    refreshSupportingRecordsRef.current = () => loadSupportingRecords().catch(() => undefined);
    setSupportingRecordsLoading(true);
    loadSupportingRecords().then(() => {
      if (generation.current === request) setSupportingRecordsError(null);
    }).catch((reason: unknown) => {
      if (generation.current === request) setSupportingRecordsError(reason instanceof Error ? reason.message : "Could not load newsroom records.");
    }).finally(() => { if (generation.current === request) setSupportingRecordsLoading(false); });
    // One timer for the whole board, paused while the tab is hidden; the user's own actions refresh through refreshBoardNowRef.
    const refresher = startBoardRefresh({ refresh: () => Promise.all([refreshSupportingRecordsRef.current(), subject === "assignment" ? undefined : pagedRefreshRef.current()]) });
    refreshBoardNowRef.current = refresher.refreshNow;
    return () => { generation.current = request + 1; refresher.stop(); refreshBoardNowRef.current = () => undefined; };
  }, [allowed, subject]);
  // Closing or switching the open record is the end of the user's edits in the panel, so show what they changed.
  const previouslySelected = useRef(selected);
  useEffect(() => {
    if (previouslySelected.current && previouslySelected.current !== selected) refreshBoardNowRef.current();
    previouslySelected.current = selected;
  }, [selected]);
  const issues = useMemo(() => {
    if (subject === "assignment") return assignmentBoardIssues;
    if (subject === "contentItem") return projectContentItemBoard({ contentItemVersions: pagedContentItems.versions, assignments });
    const versionsOnDesk = pagedContentItems.versions.filter(version => deskId && deskContainsContentItem(version, deskId));
    return [...projectContentItemBoard({ contentItemVersions: versionsOnDesk, assignments: assignments.filter(assignment => deskId && deskContainsAssignment(assignment, deskId)) }), ...deskAssignmentIssues];
  }, [assignmentBoardIssues, assignments, deskAssignmentIssues, deskId, pagedContentItems.versions, subject]);
  const loading = supportingRecordsLoading || (showsContentItems && pagedContentItems.loading);
  const error = supportingRecordsError ?? (showsContentItems ? pagedContentItems.error : null);
  const config = useMemo(() => subject === "contentItem" ? contentItemBoardConfig(issues) : subject === "desk" ? deskBoardConfig(issues) : assignmentBoardConfig(issues), [issues, subject]);
  const loadMoreWhenColumnIsNearItsEnd = (columnKey: string) => {
    if (showsContentItems && columnKey.startsWith(contentItemColumnKeyPrefix)) pagedContentItems.loadMoreForStage(columnKey.slice(contentItemColumnKeyPrefix.length));
  };
  const deskTitle = session?.shell.dashboard?.newsroomSections?.find(section => section.id === deskId)?.title ?? (deskId ? displayNewsroomSectionShortTitle({ id: deskId } as NewsroomSectionRecord) : "Desk");
  const pageTitle = subject === "contentItem" ? getContentItemName().plural : subject === "desk" ? deskTitle : "Assignments";
  const deskOptions = useMemo(() => newsroomDeskOptions(session?.shell.dashboard?.newsroomSections ?? []), [session?.shell.dashboard?.newsroomSections]);
  const changeAssignmentDesk = async (record: AssignmentRecord, deskId: string | null) => {
    await saveNewsroomAssignmentDesk(record.id, deskId);
    const moved = { ...record, sectionId: deskId, sectionKey: deskId };
    setAssignments(current => current.map(candidate => candidate.id === record.id ? moved : candidate));
    setAssignmentBoardIssues(current => current.map(candidate => candidate.nativeId === record.id ? { ...candidate } : candidate));
  };
  const issue = issues.find(item => item.id === selected);
  // Kanbus scrolls the board to its far end when a panel opens, which hides the first columns when the columns do not all fit. Keep the open card in view instead, and the
  // first column where it is when nothing needs to move.
  useEffect(() => {
    if (!selected || !issue) return;
    const body = boardBodyRef.current;
    const collection = body?.querySelector<HTMLElement>(".kb-grid");
    const open = Array.from(body?.querySelectorAll<HTMLElement>(".issue-card[data-issue-id]") ?? []).find(element => element.getAttribute("data-issue-id") === selected);
    if (!collection || !open) return;
    const frame = requestAnimationFrame(() => {
      collection.scrollLeft = 0;
      const box = collection.getBoundingClientRect();
      const card = open.getBoundingClientRect();
      if (card.right > box.right) collection.scrollLeft = card.right - box.right + 8;
    });
    return () => cancelAnimationFrame(frame);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, Boolean(issue)]);
  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab={subject === "contentItem" ? "articles" : subject === "desk" ? "desks" : "assignments"} appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle={pageTitle}
    headerActions={<NewsroomBoardHeaderActions view={view} onViewChange={setView} recordCount={loading ? null : issues.length} showsNewContentItemLink={showsContentItems} />}>
    <IssueIdFormatProvider formatIssueId={formatNativeIssueId}>
    <div className="organizer-native-board">
      {error && <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner>}
      {subject === "desk" && <IssueTypeFilter config={config} value={typeFilter} onChange={setTypeFilter} name="Record type" className="organizer-board-type-filter" />}
      <div className="organizer-board-body" data-detail-open={Boolean(issue)} ref={boardBodyRef}>
        {loading && !issues.length ? <NewsroomBoardSkeleton /> : <IssueCollection issues={issues} config={config} query={{ type: subject === "desk" ? issueTypeFromFilter(typeFilter) : boardType }} view={view} onColumnNearEnd={loadMoreWhenColumnIsNearItsEnd}
          motion={lowMotion ? STATIC_MOTION : undefined}
          collapsedColumns={columnState.collapsedColumns} onToggleCollapse={columnState.toggleColumn} initialScroll="start"
          selectedIssueId={selected} detailOpen={Boolean(issue)} onSelectIssue={item => setSelected(item.id)} ariaLabel={pageTitle}
          emptyMessage={error ? "Records could not be loaded." : "No records in this selection."} />}
        {subject !== "assignment" ? <StoryCardStars issues={issues} slots={storyCardSlots} controller={storyStars} /> : null}
        {subject !== "assignment" ? <StoryCardChecklist issues={issues} slots={storyChecklistSlots} /> : null}
        {issue && <IssueDetailPanel issue={issue} onClose={() => setSelected(null)} fields={[]}>
          {issue.kind === "contentItem"
            ? <>
              <NewsroomArticleEditor key={issue.id} articleId={decodeURIComponent(issue.href.split("/").pop() ?? "")} demo={isLocalPreviewEnabled()} embedded starsController={storyStars} />
              <StoryChecklistPanel key={`checklist-${issue.id}`} lineageId={issue.nativeId} storyIssueId={issue.id} onChanged={() => refreshBoardNowRef.current()} />
              <Link className="organizer-header-button" href={getNewsroomNavHref(issue.href)}>Open full page</Link>
            </>
            : (() => {
              const record = assignments.find(candidate => candidate.id === issue.nativeId);
              return record
                ? <NewsroomAssignmentDetail assignment={record} deskOptions={deskOptions} onDeskChange={deskId => changeAssignmentDesk(record, deskId)} pageHref={getNewsroomNavHref(issue.href)} showTitle={false} />
                : <Link href={getNewsroomNavHref(issue.href)}>Open {issue.type}</Link>;
            })()}
        </IssueDetailPanel>}
      </div>
    </div>
    </IssueIdFormatProvider>
  </NewsroomOpsShell>;
}
