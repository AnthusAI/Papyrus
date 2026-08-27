"use client";

import { Hub } from "aws-amplify/utils";
import { fetchAuthSession } from "aws-amplify/auth";
import { gsap } from "gsap";
import { Flip } from "gsap/Flip";
import { ArchiveIcon, MenuIcon, MoreHorizontalIcon, RefreshCwIcon, XIcon } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode, RefObject } from "react";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useTransition } from "react";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import {
  loadEditorAssignmentsData,
  loadEditorCategoryTreeState,
  loadEditorDoctrineRecordsData,
  loadEditorFullNewsDeskDashboard,
  loadEditorOverviewEditionData,
  loadEditorMessagesData,
  loadReferenceAttachmentsForLineageId,
  loadReferenceCitationRelations,
  loadReferenceRecordById,
  loadReferenceRecordByLineageId,
  loadStoragePathUrl,
  loadEditorUserDirectoryData,
  loadModelPayloadsForOwner,
  loadStoragePathText,
  loadEditorReferencesData,
  loadEditorProcedureData,
  loadEditorSemanticRelationsData,
  loadEditionForumThreads,
  loadInsightForumThreadById,
  loadInsightForumThreads,
  loadNewsroomAssignmentPage,
  loadNewsroomMessagePage,
  loadNewsroomReferencePage,
  loadNewsroomSemanticNodePage,
  appendForumThreadMessageRecord,
  appendInsightThreadReplyRecord,
  createSectionForumThreadRecord,
  deleteForumThreadMessageRecord,
  deleteInsightThreadMessageRecord,
  ensureEditionForumThreadRecord,
  publishProcedureVersionRecord,
  runNewsroomKnowledgeQuery,
  saveProcedureDefinitionRecord,
  saveProcedureVersionDraftRecord,
  selectRootDeskCategoriesForDoctrine,
  startProcedureRunRecord,
  uploadModelPayloadForOwner,
  type ForumThreadWithMessages,
  type KnowledgeQueryResponse,
  type NewsroomRecordPage,
} from "./news-desk-taxonomy-client";
import { listConsoleThreads } from "../lib/console-chat-client";
import {
  effectiveAssignmentsIndexFilters,
  effectiveMessagesIndexFilters,
  effectiveReferencesIndexFilters,
  normalizeReferenceIndexOrder,
  readAssignmentsIndexFilters,
  readInsightsIndexFilters,
  readMessagesIndexFilters,
  readReferencesIndexFilters,
  effectiveInsightsIndexFilters,
  parseInsightThreadIdFromNewsroomPathname,
  referencesStatusFromUrl,
  referencesStatusToUrl,
  type ReferenceIndexOrder,
  parseReferenceLineageIdFromNewsroomPathname,
  syncBrowserNewsroomIndexUrl,
} from "../lib/newsroom-index-filters";
import { buildNewsroomKnowledgeQueryInput, type NewsroomKnowledgeQueryAnchor as KnowledgeQueryAnchor, type NewsroomKnowledgeQueryTarget as KnowledgeQueryTarget } from "../lib/newsroom-knowledge-query-request";
import { NewsroomConsoleProgressToggle, PapyrusConsoleChatIcon, usePapyrusConsole } from "./papyrus-console-shell";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { ReferenceSourcePreview } from "./reference-source-preview";
import type { ReaderAuthSnapshot } from "./reader-auth-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import type {
  AssignmentEventRecord,
  AssignmentRecord,
  EditionRecord,
  EditionSlotRecord,
  AnalysisProfileSummary,
  CategorySteeringArtifact,
  CategorySteeringCorpus,
  CategorySteeringDashboard,
  CategorySteeringImportRun,
  CategorySteeringProposal,
  CategorySteeringCategoryTree,
  CategorySteeringCategoryTreeNode,
  CategorySteeringCategory,
  CategorySteeringCategorySet,
  CategoryKeywordRecord,
  DoctrineRecord,
  MessageRecord,
  ModelAttachmentRecord,
  HydratedModelPayload,
  NewsroomSummaryRecord,
  LexicalSteeringRuleRecord,
  NewsroomSectionRecord,
  ProcedureDefinitionRecord,
  ProcedureRunRecord,
  ProcedureVersionRecord,
  ReferenceAttachmentRecord,
  ReferenceRecord,
  SemanticNodeRecord,
  SemanticRelationRecord,
  UserDirectoryEntry,
} from "../lib/category-repository";
import {
  type DoctrineKind,
  DOCTRINE_DEFINITION_BY_KIND,
  DOCTRINE_DEFINITIONS,
  DOCTRINE_ITEM_STATUS,
  DOCTRINE_ITEM_TYPE,
  DOCTRINE_ITEM_TYPE_STATUS,
  buildCategoryDoctrineDefinition,
  categoryDoctrineEditorialValue,
  type DoctrineCategory,
  doctrineBodyToText,
  doctrineEditorialValue,
  doctrineTextToBody,
} from "../lib/doctrine";
import {
  createSemanticGraphSnapshot,
  newsDeskHrefForSemanticObject,
  relationTypeKey,
  type SemanticNeighborGroup,
  type SemanticObjectSummary,
} from "../lib/semantic-graph";
import {
  REFERENCE_REJECTION_REASON_CODES,
  referenceCurationStatusForAction,
} from "../lib/reference-policy";
import {
  referenceDisplaySummary,
  referenceMetadataField,
  resolveCanonicalReferenceLineage,
} from "../lib/reference-display";
import {
  buildCategoryDrilldownContext,
  buildTopicDrilldownContext,
  categoryDrilldownHref,
  categoryLineageId,
  referencesForCategoryContext,
  semanticNodesForCategoryContext,
  topicHref,
  uniqueNeighborGroupsForCategoryContext,
  type CategoryDrilldownContext,
} from "../lib/newsroom-category-drilldown";
import type { NewsDeskShellState } from "../lib/news-desk-session";
import {
  resolveNewsroomCardTemplate,
  type NewsroomCardSpan,
  type NewsroomCardTemplateRole,
} from "../lib/newsroom-card-layout";
import {
  buildReportingStoryBudget,
  type ReportingStoryBudgetCandidate,
  type ReportingStoryBudgetPhase,
  type ReportingStoryBudgetSlot,
  type ReportingStoryBudgetSection,
} from "../lib/reporting-story-budget";
import {
  buildForumThreadUrl,
  buildInsightThreadUrl,
  getForumMessageAnchorId,
  isForumThreadId,
  parseForumMessageAnchorFromHash,
  pushForumThreadUrl,
  pushInsightThreadUrl,
  readCurrentForumRoute,
} from "../lib/newsroom-forum-routes";

gsap.registerPlugin(Flip);

type ActionState = {
  id: string;
  message: string;
  tone: "ok" | "error" | "pending";
};

type ReferenceQualityActionState = {
  displayedStars: number;
  effectiveStatus: string;
  message: string;
  referenceId: string;
  requestedRating: number;
  showUnsetStars: boolean;
  tone: ActionState["tone"];
};

type ReviewAction = "accept" | "reject" | "defer" | "edit";
type ProposalReviewInput = {
  note?: string | null;
  displayName?: string | null;
  shortTitle?: string | null;
  subtitle?: string | null;
  description?: string | null;
  aliases?: string[] | null;
  seedItemIds?: string[] | null;
  holdoutItemIds?: string[] | null;
};
type ReferenceCurationAction = "accept" | "reject" | "archive";
type ReferenceRejectionReasonCode = typeof REFERENCE_REJECTION_REASON_CODES[number];
type TopicLabelAction = "manual_label" | "accept_prediction" | "reject_prediction" | "unlabel";
type AssignmentAction = "claim" | "release" | "complete" | "cancel" | "reopen" | "retry";
type ReportingPacketReviewDecision = "select" | "merge" | "brief" | "hold" | "kill";
type AssignmentDeskViewMode = "queue" | "budget";
type UserRoleAction = "grant" | "revoke";
type AdministrationPanel = "users" | "policies" | "sections" | "procedures";
export type NewsDeskTab = "overview" | "desks" | "topics" | "concepts" | "references" | "insights" | "messages" | "assignments" | "administration" | "search";
type LexicalRuleScope = "publication" | "corpus" | "classifier" | "category";
type AnalysisReindexMode = "online-update" | "classifier-retrain" | "scoped-topic-rebuild" | "entity-graph-rebuild" | "generated-analysis-rebuild";
type ReferenceProcessingStatus = "created" | "processable" | "processed" | "blocked";
type AnalysisReindexDraft = {
  corpusKey: string;
  mode: AnalysisReindexMode;
  overrides: Record<string, unknown>;
};
type DraftCategoryInput = Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description"> & {
  parentCategoryKey?: string | null;
  note?: string | null;
};
type TopicDraftModalState =
  | { kind: "create"; parentCategoryKey?: string | null }
  | { kind: "edit"; category: CategorySteeringCategory }
  | { kind: "archive"; category: CategorySteeringCategory }
  | { kind: "promote" }
  | { kind: "discard" };
type TopicProposalEditState = {
  proposal: CategorySteeringProposal;
};
type AnalysisCommandPlanEntry = {
  label: string;
  cwd: string;
  executable: string;
  args: string[];
  metadata?: Record<string, unknown>;
};
type NewsroomDataGridColumn = {
  key: string;
  label: string;
};
type NewsroomDataGridMetric = {
  key: string;
  label: string;
  count: number;
};
type NewsroomDataGridRow = {
  id: string;
  cells: ReactNode[];
};
type NewsroomCardRecord = {
  id: string;
  ariaLabel?: string;
  body?: ReactNode;
  dataAttributes?: Record<string, boolean | number | string | undefined>;
  href?: string;
  kicker?: ReactNode;
  meta: ReactNode[];
  span?: NewsroomCardSpan;
  stamp?: ReactNode;
  templateRole?: NewsroomCardTemplateRole;
  title: ReactNode;
};
type ConsoleThreadSummary = {
  id: string;
  threadKind: string;
  status: string;
  title: string;
  summary?: string | null;
  primaryAnchorKey?: string | null;
  createdByLabel?: string | null;
  messageCount?: number | null;
  lastMessageAt?: string | null;
  createdAt: string;
  updatedAt: string;
  newsroomFeedKey?: string | null;
};
type NewsroomDetailAction = {
  ariaLabel?: string;
  icon?: ReactNode;
  key: string;
  label: string;
  disabled?: boolean;
  onSelect: () => void;
};

type InsightTarget = {
  kind: "assignment" | "category" | "item" | "newsroomSection" | "reference" | "semanticNode";
  id: string;
  lineageId: string;
  title: string;
  subtitle?: string | null;
  versionNumber?: number | null;
};

type InsightComposerControl = {
  action: NewsroomDetailAction;
  dialog: ReactNode;
  error: string | null;
  loading: boolean;
};

type NewsroomSearchRequest = {
  anchor?: KnowledgeQueryAnchor | null;
  from?: string | null;
  maxTokens: number;
  semanticQuery: string;
};

type KnowledgeQueryControl = {
  action: NewsroomDetailAction;
  clear: () => void;
  dialog: ReactNode;
  error: string | null;
  loading: boolean;
  result: KnowledgeQueryResponse | null;
};

type NewsroomRouteSearchControl = {
  dialog: ReactNode;
  open: () => void;
};

type NewsroomPagedRows<T> = {
  items: T[];
  nextToken?: string | null;
  hasMore: boolean;
  isLoading: boolean;
  isLoadingMore: boolean;
  error: string | null;
};
type LexicalRuleDraft = {
  term: string;
  scope: LexicalRuleScope;
  corpusId?: string | null;
  classifierId?: string | null;
  categorySetId?: string | null;
  categoryKey?: string | null;
  note?: string | null;
};

const REFERENCE_PAGE_SIZE = 25;
const TOPIC_REFERENCE_PAGE_SIZE = 12;
const NEWSROOM_SECTION_SHORT_TITLE_FALLBACKS: Record<string, string> = {
  arts: "Creative Work",
  business: "Market Structure",
  education: "Learning Systems",
  health: "Clinical Systems",
  history: "Prior Lineage",
  "law-policy": "Rules & Power",
  labor: "Work Change",
  methods: "Applied Practice",
  news: "Trends & Analysis",
  opinion: "Editorial Voice",
  science: "New Findings",
  security: "Threat Awareness",
  sports: "Signal & Edge",
  technology: "Infrastructure Landscape",
  world: "Global Affairs",
};
const ANALYSIS_REINDEX_MODES: AnalysisReindexMode[] = [
  "online-update",
  "classifier-retrain",
  "scoped-topic-rebuild",
  "entity-graph-rebuild",
  "generated-analysis-rebuild",
];

export type NewsDeskSelection = {
  assignment?: string | null;
  reference?: string | null;
  category?: string | null;
  node?: string | null;
  message?: string | null;
  user?: string | null;
  item?: string | null;
  panel?: string | null;
  searchQuery?: string | null;
  searchAnchorKind?: string | null;
  searchAnchorId?: string | null;
  searchAnchorLineageId?: string | null;
  searchMaxTokens?: string | null;
  searchFrom?: string | null;
  assignmentView?: string | null;
  forumThread?: string | null;
};

type CategoryReviewResponse = {
  data?: {
    ok?: boolean | null;
    status?: string | null;
    proposalId?: string | null;
    decisionId?: string | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceReviewResponse = {
  data?: {
    ok?: boolean | null;
    action?: string | null;
    referenceId?: string | null;
    status?: string | null;
    reasonCode?: string | null;
    messageId?: string | null;
    relationId?: string | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceQualityResponse = {
  data?: {
    ok?: boolean | null;
    referenceId?: string | null;
    rating?: number | null;
    status?: string | null;
    relationId?: string | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceInsightResponse = {
  data?: {
    ok?: boolean | null;
    referenceId?: string | null;
    messageId?: string | null;
    relationId?: string | null;
    status?: string | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceCorpusMoveResponse = {
  data?: {
    ok?: boolean | null;
    referenceId?: string | null;
    referenceLineageId?: string | null;
    previousReferenceId?: string | null;
    previousCorpusId?: string | null;
    corpusId?: string | null;
    status?: string | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceCurationStartResponse = {
  data?: {
    ok?: boolean | null;
    referenceId?: string | null;
    assignmentId?: string | null;
    status?: string | null;
    runId?: string | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceCurationStatusResponse = {
  data?: {
    ok?: boolean | null;
    referenceId?: string | null;
    assignmentId?: string | null;
    status?: string | null;
    runId?: string | null;
    lifecycleStatus?: string | null;
    stageStatuses?: Record<string, unknown> | null;
    changedOutputs?: Record<string, unknown> | null;
    error?: Record<string, unknown> | null;
  } | null;
  errors?: Array<{ message?: string | null } | string | null> | null;
};

type ReferenceCurationRunStatus = {
  assignmentId: string;
  status: string;
  lifecycleStatus: string;
  runId?: string | null;
  stageStatuses: Record<string, unknown>;
  changedOutputs: Record<string, unknown>;
  error: Record<string, unknown> | null;
  updatedAt: string;
};

type MergeSelection = {
  source: UserDirectoryEntry;
  targetUserKey: string;
  reason: string;
  notice?: string;
};

type DoctrineEditorState = Record<DoctrineKind, string>;

function useNewsroomRhythmOverlay() {
  const [showRhythmOverlay, setShowRhythmOverlay] = useState(false);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableEventTarget(event.target)) return;

      if ((event.key === "=" || event.code === "Equal") && event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setShowRhythmOverlay((current) => !current);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return showRhythmOverlay;
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const handleChange = () => setMatches(mediaQuery.matches);
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [query]);

  return matches;
}

function isEditableEventTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;

  const tagName = target.tagName.toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select") return true;

  return target.isContentEditable || target.closest("[contenteditable='true']") !== null;
}

type NewsDeskDrawerController = {
  close: () => void;
  drawerId: string;
  firstLinkRef: RefObject<HTMLAnchorElement | null>;
  isDocked: boolean;
  isModal: boolean;
  open: boolean;
  setOpen: (value: boolean) => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
};

function useNewsDeskDrawerController(): NewsDeskDrawerController {
  const pathname = usePathname();
  const isDocked = useMediaQuery("(min-width: 1100px)");
  const isModal = !isDocked;
  const drawerId = useId();
  const lastPathnameRef = useRef(pathname);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const firstLinkRef = useRef<HTMLAnchorElement | null>(null);
  const [open, setOpen] = useState(false);
  const shouldRestoreFocusRef = useRef(false);

  const close = useCallback(() => {
    if (!open) return;
    shouldRestoreFocusRef.current = true;
    setOpen(false);
  }, [open]);

  useEffect(() => {
    if (lastPathnameRef.current === pathname) return;
    lastPathnameRef.current = pathname;
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open || !isModal) return;
    requestAnimationFrame(() => {
      firstLinkRef.current?.focus();
    });
  }, [isModal, open]);

  useEffect(() => {
    if (open || !shouldRestoreFocusRef.current) return;
    shouldRestoreFocusRef.current = false;
    triggerRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close();
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [close, open]);

  useEffect(() => {
    if (!open || !isModal) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isModal, open]);

  return {
    close,
    drawerId,
    firstLinkRef,
    isDocked,
    isModal,
    open,
    setOpen,
    triggerRef,
  };
}

function inferNewsDeskTabFromPathname(pathname: string | null): NewsDeskTab | null {
  if (!pathname || !pathname.startsWith("/newsroom")) return null;
  if (pathname === "/newsroom" || pathname === "/newsroom/") return "overview";
  if (pathname.startsWith("/newsroom/messages")) return "messages";
  if (pathname.startsWith("/newsroom/insights")) return "insights";
  if (pathname.startsWith("/newsroom/assignments")) return "assignments";
  if (pathname.startsWith("/newsroom/references")) return "references";
  if (pathname.startsWith("/newsroom/topics")) return "topics";
  if (pathname.startsWith("/newsroom/concepts")) return "concepts";
  if (pathname.startsWith("/newsroom/administration")) return "administration";
  if (pathname.startsWith("/newsroom/search")) return "search";
  return null;
}

const TAILORED_TOPIC_PROPOSAL_KINDS = new Set([
  "new-category",
  "rename-category",
  "merge-category",
  "deprecate-category",
  "seed-change",
  "holdout-change",
  "category-display-copy-edit",
  "category-copy-edit",
  "display-copy-edit",
]);

const NEWS_DESK_TABS: Array<{ id: NewsDeskTab; label: string; detail: string; href: string }> = [
  { id: "messages", label: "Messages", detail: "Commentary", href: "/newsroom/messages" },
  { id: "insights", label: "Insights", detail: "Research threads", href: "/newsroom/insights" },
  { id: "assignments", label: "Assignments", detail: "Work Desk", href: "/newsroom/assignments" },
  { id: "references", label: "References", detail: "Knowledge Base", href: "/newsroom/references" },
  { id: "topics", label: "Topics", detail: "Taxonomy", href: "/newsroom/topics" },
  { id: "concepts", label: "Concepts", detail: "Ontology", href: "/newsroom/concepts" },
  { id: "administration", label: "Administration", detail: "Users, Policies & Procedures", href: "/newsroom/administration" },
];

const TAXONOMY_PROPOSAL_KINDS = new Set([
  "create-category",
  "move-category",
  "archive-category",
  "merge-categories",
  "split-category",
]);
const TOPIC_PROPOSAL_BLOCKED_APPLY_KINDS = new Set([
  "merge-category",
  "merge-categories",
  "split-category",
  "archive-category",
  "deprecate-category",
]);

const USER_POOL_AUTH_MODE = "userPool";
type SemanticGraph = ReturnType<typeof createSemanticGraphSnapshot>;
type ReferenceSubscriptionInput = {
  filter?: {
    newsroomFeedKey?: {
      eq?: string;
    };
  };
};
type ReferenceSubscription = {
  unsubscribe: () => void;
};
type RealtimeSubscriptionStatus = "idle" | "connected" | "connecting" | "reconnecting" | "stale" | "error";
type SubscriptionObserver = {
  next: (value: unknown) => void;
  error?: (error: unknown) => void;
};
type ModelSubscriptionFactory = {
  subscribe: (observer: SubscriptionObserver) => ReferenceSubscription;
};
type ReferenceSubscriptionModel = {
  onCreate: (input?: ReferenceSubscriptionInput) => ModelSubscriptionFactory;
  onUpdate: (input?: ReferenceSubscriptionInput) => ModelSubscriptionFactory;
  onDelete?: (input?: ReferenceSubscriptionInput) => ModelSubscriptionFactory;
};
type SemanticRelationSubscriptionModel = {
  onCreate: () => ModelSubscriptionFactory;
  onUpdate: () => ModelSubscriptionFactory;
  onDelete?: () => ModelSubscriptionFactory;
};
type ModelAttachmentSubscriptionModel = {
  onCreate: () => ModelSubscriptionFactory;
  onUpdate: () => ModelSubscriptionFactory;
  onDelete?: () => ModelSubscriptionFactory;
};

function NewsDeskTabLink({
  active,
  count,
  countSlot = true,
  countVisible = true,
  countMissing = false,
  demo,
  tab,
}: {
  active: boolean;
  count: number | null;
  countSlot?: boolean;
  countVisible?: boolean;
  countMissing?: boolean;
  demo?: boolean;
  tab: { id: NewsDeskTab; label: string; detail: string; href: string };
}) {
  const countParts = typeof count === "number" ? formatCompactCountParts(count) : null;
  const countContentRef = useRef<HTMLSpanElement | null>(null);
  const hasAnimatedCountRef = useRef(false);

  useLayoutEffect(() => {
    const countContent = countContentRef.current;
    if (!countContent) {
      hasAnimatedCountRef.current = false;
      return;
    }

    gsap.killTweensOf(countContent);

    if (!countVisible) {
      hasAnimatedCountRef.current = false;
      countContent.style.opacity = "";
      countContent.style.visibility = "";
      return;
    }

    if (!hasAnimatedCountRef.current) {
      hasAnimatedCountRef.current = true;
      gsap.fromTo(
        countContent,
        { autoAlpha: 0 },
        { autoAlpha: 1, duration: 1.35, ease: "sine.out" },
      );
      return;
    }

    gsap.set(countContent, { autoAlpha: 1 });
  }, [countVisible, countMissing, countParts?.suffix, countParts?.value]);

  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`news-desk-tab${active ? " news-desk-tab--active" : ""}`}
      data-count-slot={countSlot ? "true" : "false"}
      data-news-desk-tab={tab.id}
      href={getNewsDeskTabHref(tab.href, demo)}
    >
      {countSlot ? (
        <strong
          className="news-desk-tab__count"
          aria-label={
            countVisible
              ? countMissing
                ? `${tab.label} count unavailable`
                : `${formatCompactCount(count ?? 0)} ${tab.label.toLowerCase()}`
              : `${tab.label} count loading`
          }
          data-count-visible={countVisible ? "true" : "false"}
        >
          {countVisible ? (
            <span className="news-desk-tab__count-content" ref={countContentRef}>
              {countMissing ? (
                <span className="news-desk-tab__count-value">?</span>
              ) : countParts ? (
                <>
                  <span className="news-desk-tab__count-value">{countParts.value}</span>
                  {countParts.suffix ? <span className="news-desk-tab__count-suffix">{countParts.suffix}</span> : null}
                </>
              ) : null}
            </span>
          ) : (
            <span className="news-desk-tab__count-content" ref={countContentRef} aria-hidden="true" />
          )}
        </strong>
      ) : null}
      <span className="news-desk-tab__text">
        <span>{tab.label}</span>
        <small>{tab.detail}</small>
      </span>
    </Link>
  );
}

function NewsDeskDrawerTrigger({ controller }: { controller: NewsDeskDrawerController }) {
  return (
    <button
      aria-controls={controller.drawerId}
      aria-expanded={controller.open}
      aria-label="Open newsroom sections navigation"
      className="news-desk-hamburger"
      onClick={() => controller.setOpen(!controller.open)}
      ref={controller.triggerRef}
      type="button"
    >
      <MenuIcon aria-hidden="true" className="news-desk-hamburger__icon news-desk-search-mark__icon" size={16} />
      <span>Sections</span>
    </button>
  );
}

function NewsDeskDrawerPanel({
  activeTab,
  controller,
  demo = false,
}: {
  activeTab: NewsDeskTab | null;
  controller: NewsDeskDrawerController;
  demo?: boolean;
}) {
  const closeLabel = controller.isModal ? "Close sections menu" : "Hide sections menu";

  return (
    <>
      <button
        aria-hidden={!controller.isModal || !controller.open}
        className="news-desk-drawer-backdrop"
        data-open={controller.open ? "true" : "false"}
        data-visible={controller.isModal ? "true" : "false"}
        onClick={controller.close}
        tabIndex={controller.open && controller.isModal ? 0 : -1}
        type="button"
      />
      <aside
        aria-label="Newsroom sections"
        aria-modal={controller.isModal ? true : undefined}
        className="news-desk-drawer"
        data-mode={controller.isDocked ? "docked" : "modal"}
        data-open={controller.open ? "true" : "false"}
        id={controller.drawerId}
        role={controller.isModal ? "dialog" : "navigation"}
      >
        <div className="news-desk-drawer__header">
          <p className="news-desk-drawer__title">Sections</p>
          <button aria-label={closeLabel} className="news-desk-drawer__close" onClick={controller.close} type="button">
            <XIcon aria-hidden="true" className="news-desk-search-mark__icon" size={16} />
          </button>
        </div>
        <nav className="news-desk-drawer__nav" aria-label="Newsroom section links">
          {NEWS_DESK_TABS.map((tab, index) => {
            const isActive = activeTab === tab.id || (activeTab === "desks" && tab.id === "topics");
            return (
              <Link
                aria-current={isActive ? "page" : undefined}
                className="news-desk-drawer__link"
                data-active={isActive ? "true" : "false"}
                href={getNewsDeskTabHref(tab.href, demo)}
                key={tab.id}
                onClick={controller.close}
                ref={index === 0 ? controller.firstLinkRef : undefined}
              >
                <span className="news-desk-drawer__link-label">{tab.label}</span>
                <span className="news-desk-drawer__link-detail">{tab.detail}</span>
              </Link>
            );
          })}
        </nav>
      </aside>
    </>
  );
}

export function NewsDeskWorkspace({
  analysisProfiles = [],
  configuredCorpora = [],
  dashboard,
  initialTab = "overview",
  initialSelection = {},
  sectionPageId = null,
}: {
  analysisProfiles?: AnalysisProfileSummary[];
  configuredCorpora?: CategorySteeringCorpus[];
  dashboard: CategorySteeringDashboard | null;
  initialTab?: NewsDeskTab;
  initialSelection?: NewsDeskSelection;
  sectionPageId?: string | null;
}) {
  const session = useOptionalNewsDeskClient();
  const sessionDashboard = useMemo(() => {
    if (!session?.shell.dashboard) return null;
    const fallbackSections = dashboard?.newsroomSections ?? [];
    const fallbackProposals = dashboard?.proposals ?? [];
    const needsSectionFallback = session.shell.dashboard.newsroomSections.length === 0 && fallbackSections.length > 0;
    const needsProposalFallback = session.shell.dashboard.proposals.length === 0 && fallbackProposals.length > 0;
    if (!needsSectionFallback && !needsProposalFallback) return session.shell.dashboard;
    return {
      ...session.shell.dashboard,
      newsroomSections: needsSectionFallback ? fallbackSections : session.shell.dashboard.newsroomSections,
      proposals: needsProposalFallback ? fallbackProposals : session.shell.dashboard.proposals,
    };
  }, [dashboard?.newsroomSections, dashboard?.proposals, session?.shell.dashboard]);
  const showSectionTabs = initialTab === "overview" && !sectionPageId;

  if (dashboard?.isDemo) {
    return (
      <NewsDeskDashboard
        analysisProfiles={analysisProfiles}
        configuredCorpora={configuredCorpora}
        canEdit
        dashboard={dashboard}
        editorShellReady
        initialSelection={initialSelection}
        initialTab={initialTab}
        sectionPageId={sectionPageId}
        authState={{ status: "signedIn", label: "Demo Desk" }}
        isRefreshing={false}
        shellError={null}
      />
    );
  }

  if (session && sessionDashboard) {
    return (
      <NewsDeskDashboard
        analysisProfiles={analysisProfiles}
        configuredCorpora={configuredCorpora}
        canEdit
        dashboard={sessionDashboard}
        editorShellReady={session.shell.phase === "ready"}
        initialSelection={initialSelection}
        initialTab={initialTab}
        sectionPageId={sectionPageId}
        authState={session.shell.auth}
        isRefreshing={session.shell.phase === "refreshing"}
        shellError={session.shell.error}
        onRefreshAssignments={session.refreshAssignments}
        onRefreshDoctrineRecords={session.refreshDoctrineRecords}
        onRefreshUserDirectory={session.refreshUserDirectory}
      />
    );
  }

  if (dashboard?.isPublicSkeleton && session?.shell.phase !== "ready") {
    return <NewsDeskAccessGate shell={session?.shell ?? null} showSectionTabs={showSectionTabs} />;
  }

  if (dashboard) {
    return (
      <NewsDeskDashboard
        analysisProfiles={analysisProfiles}
        configuredCorpora={configuredCorpora}
        canEdit={false}
        dashboard={dashboard}
        editorShellReady={false}
        initialSelection={initialSelection}
        initialTab={initialTab}
        sectionPageId={sectionPageId}
        authState={session?.shell.auth ?? { status: "signedOut", label: "Signed out" }}
        isRefreshing={session?.shell.phase === "refreshing"}
        shellError={session?.shell.error ?? null}
      />
    );
  }

  return <NewsDeskAccessGate shell={session?.shell ?? null} showSectionTabs={showSectionTabs} />;
}

function NewsDeskDashboard({
  analysisProfiles,
  canEdit,
  configuredCorpora,
  dashboard,
  editorShellReady = false,
  initialTab,
  initialSelection,
  sectionPageId,
  authState,
  isRefreshing,
  shellError,
  onRefreshAssignments,
  onRefreshDoctrineRecords,
  onRefreshUserDirectory,
}: {
  analysisProfiles: AnalysisProfileSummary[];
  canEdit: boolean;
  configuredCorpora: CategorySteeringCorpus[];
  dashboard: CategorySteeringDashboard;
  editorShellReady?: boolean;
  initialTab: NewsDeskTab;
  initialSelection: NewsDeskSelection;
  sectionPageId?: string | null;
  authState: ReaderAuthSnapshot;
  isRefreshing: boolean;
  shellError: string | null;
  onRefreshAssignments?: () => Promise<void>;
  onRefreshDoctrineRecords?: () => Promise<void>;
  onRefreshUserDirectory?: () => Promise<void>;
}) {
  const dataClient = useMemo(() => generateClient<Schema>(), []);
  const referenceSubscriptionClient = useMemo(
    () => generateClient<Schema>({ authMode: USER_POOL_AUTH_MODE }),
    [],
  );
  const activeTab = initialTab;
  const pathname = usePathname();
  const pathnameReferenceLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const isSectionPage = Boolean(sectionPageId);
  const drawerController = useNewsDeskDrawerController();
  const [corpora, setCorpora] = useState(dashboard.corpora);
  const [importRuns, setImportRuns] = useState(dashboard.importRuns);
  const [categorySets, setCategorySets] = useState(dashboard.categorySets);
  const [artifacts, setArtifacts] = useState(dashboard.artifacts);
  const [canonicalCorpusId, setCanonicalCorpusId] = useState(dashboard.canonicalCorpusId ?? null);
  const [canonicalCategorySetId, setCanonicalCategorySetId] = useState(dashboard.canonicalCategorySetId ?? null);
  const [categorys, setCategorys] = useState(dashboard.categorys);
  const [categoryTrees, setTaxonomies] = useState(dashboard.categoryTrees);
  const [categoryNodes, setCategoryTreeNodes] = useState(dashboard.categoryNodes);
  const [categoryKeywords, setCategoryKeywords] = useState(dashboard.categoryKeywords);
  const [lexicalSteeringRules, setLexicalSteeringRules] = useState(dashboard.lexicalSteeringRules);
  const [categoryTreeLoadError, setCategoryTreeLoadError] = useState<string | null>(null);
  const [proposals, setProposals] = useState(dashboard.proposals);
  const [references, setReferences] = useState(dashboard.references);
  const [summary, setSummary] = useState<NewsroomSummaryRecord | null>(dashboard.summary ?? null);
  const [referenceAttachments, setReferenceAttachments] = useState(dashboard.referenceAttachments);
  const [messages, setMessages] = useState(dashboard.messages);
  const [semanticRelations, setSemanticRelations] = useState(dashboard.semanticRelations);
  const [semanticNodes, setSemanticNodes] = useState(dashboard.semanticNodes);
  const [assignments, setAssignments] = useState(dashboard.assignments);
  const [assignmentEvents, setAssignmentEvents] = useState(dashboard.assignmentEvents);
  const [editionSlots, setEditionSlots] = useState(dashboard.editionSlots ?? []);
  const [doctrineRecords, setDoctrineRecords] = useState(dashboard.doctrineRecords);
  const fallbackNewsroomSections = useMemo(
    () => normalizeNewsroomSectionsWithFallback(dashboard.newsroomSections),
    [dashboard.newsroomSections],
  );
  const [newsroomSections, setNewsroomSections] = useState(fallbackNewsroomSections);
  const [procedureDefinitions, setProcedureDefinitions] = useState(dashboard.procedureDefinitions ?? []);
  const [procedureVersions, setProcedureVersions] = useState(dashboard.procedureVersions ?? []);
  const [procedureRuns, setProcedureRuns] = useState(dashboard.procedureRuns ?? []);
  const [userDirectory, setUserDirectory] = useState(dashboard.userDirectory);
  const [actionState, setActionState] = useState<ActionState | null>(null);
  const [referenceQualityActionState, setReferenceQualityActionState] = useState<ReferenceQualityActionState | null>(null);
  const [referenceCurationRunsByLineage, setReferenceCurationRunsByLineage] = useState<Record<string, ReferenceCurationRunStatus>>({});
  const [mergeSelection, setMergeSelection] = useState<MergeSelection | null>(null);
  const [isPending, startTransition] = useTransition();
  const controlsDisabled = isPending || !canEdit;
  const showRhythmOverlay = useNewsroomRhythmOverlay();
  const initialAdministrationPanel = normalizeAdministrationPanel(initialSelection.panel);
  const [administrationPanel, setAdministrationPanel] = useState<AdministrationPanel>(initialAdministrationPanel);
  const [doctrineDrafts, setDoctrineDrafts] = useState<DoctrineEditorState>(() => buildDoctrineEditorState(dashboard.doctrineRecords));
  const [loadedSections, setLoadedSections] = useState<Record<string, boolean>>({
    assignments: dashboard.assignments.length > 0,
    messages: dashboard.messages.length > 0,
    references: dashboard.isDemo ? dashboard.references.length > 0 : false,
    sections: dashboard.isDemo || !canEdit,
    semanticRelations: dashboard.semanticRelations.length > 0,
    fullDashboard: !dashboard.summary && !dashboard.isPublicSkeleton,
  });
  const [hasRefreshedNewsroomSections, setHasRefreshedNewsroomSections] = useState(false);
  const [hasHydratedReferences, setHasHydratedReferences] = useState(
    dashboard.isDemo ? dashboard.references.length > 0 : false,
  );
  const [referencesRealtimeStatus, setReferencesRealtimeStatus] = useState<RealtimeSubscriptionStatus>("idle");
  const [referencesRealtimeError, setReferencesRealtimeError] = useState<string | null>(null);
  const referencesRef = useRef(references);

  useEffect(() => {
    referencesRef.current = references;
  }, [references]);

  useEffect(() => {
    if (referenceQualityActionState?.tone !== "ok") return;
    const qualityState = referenceQualityActionState;
    const timeout = window.setTimeout(() => {
      setReferenceQualityActionState((current) => (current === qualityState ? null : current));
    }, 1600);
    return () => window.clearTimeout(timeout);
  }, [referenceQualityActionState]);

  const categoryProposals = proposals.filter(isTailoredCategoryProposal);
  const genericProposals = proposals.filter((proposal) => !isTailoredCategoryProposal(proposal));
  const activeCategorySet = useMemo(() => (
    categorySets.find((categorySet) => categorySet.id === canonicalCategorySetId && isCurrentCategorySet(categorySet))
    ?? categorySets.find(isCurrentCategorySet)
    ?? null
  ), [canonicalCategorySetId, categorySets]);
  const canonicalCorpus = useMemo(() => (
    corpora.find((corpus) => corpus.id === canonicalCorpusId)
    ?? (activeCategorySet ? corpora.find((corpus) => corpus.id === activeCategorySet.corpusId) : undefined)
    ?? null
  ), [activeCategorySet, canonicalCorpusId, corpora]);
  const canonicalCategorys = useMemo(() => (
    activeCategorySet ? categorys.filter((category) => (
      category.categorySetId === activeCategorySet.id
      && category.status !== "deprecated"
      && category.status !== "archived"
      && category.versionState !== "superseded"
    )) : []
  ), [activeCategorySet, categorys]);
  const activeCategoryTree = useMemo(
    () => selectActiveCategoryTree(categoryTrees, activeCategorySet?.id ?? null, canonicalCorpus?.id ?? null),
    [activeCategorySet?.id, canonicalCorpus?.id, categoryTrees],
  );
  const activeCategoryTreeNodes = useMemo(() => (
    activeCategoryTree ? categoryNodes.filter((node) => node.categorySetId === activeCategoryTree.id && node.status !== "deprecated") : []
  ), [activeCategoryTree, categoryNodes]);
  const rootDeskCategories = useMemo(() => selectRootDeskCategoriesForDoctrine({
    categorys,
    categoryNodes: activeCategoryTreeNodes,
    categorySetId: activeCategorySet?.id ?? null,
  }), [activeCategorySet?.id, activeCategoryTreeNodes, categorys]);
  const acceptedDoctrineCategories = useMemo(() => (
    selectAcceptedCategoriesForDoctrine({
      categorys,
      categoryNodes: activeCategoryTreeNodes,
      categorySetId: activeCategorySet?.id ?? null,
    })
  ), [activeCategorySet?.id, activeCategoryTreeNodes, categorys]);
  const summaryStatus = newsroomSummaryStatus({ summary, summaryStatus: dashboard.summaryStatus });
  const activeNewsroomSection = sectionPageId
    ? newsroomSections.find((section) => section.id === sectionPageId && section.enabled !== false && section.enabledStatus !== "disabled") ?? null
    : null;
  const mastheadTitle = activeNewsroomSection?.title ?? (isSectionPage ? "SECTION" : "NEWSROOM");
  const tabCounts = useMemo<Record<NewsDeskTab, number | null>>(() => ({
    overview: 0,
    desks: summaryCountFromRecord(summary, "categories"),
    messages: summaryCountFromRecord(summary, "messages"),
    insights: summary?.facets?.messages?.byKind?.insight
      ?? summary?.messageKindCounts?.insight
      ?? null,
    assignments: summaryCountFromRecord(summary, "assignments"),
    references: summaryCountFromRecord(summary, "references"),
    topics: summaryCountFromRecord(summary, "categories"),
    concepts: summaryCountFromRecord(summary, "semanticNodes"),
    administration: userDirectory.length + doctrineRecords.length + newsroomSections.length + procedureDefinitions.length,
    search: 0,
  }), [
    doctrineRecords.length,
    newsroomSections.length,
    procedureDefinitions.length,
    summary,
    userDirectory.length,
  ]);
  const graph = useMemo(() => createSemanticGraphSnapshot({
    references,
    categories: mergeCategoryRecords(categorys, activeCategoryTreeNodes),
    semanticNodes,
    messages,
    newsroomSections,
    semanticRelations,
    assignments,
    referenceAttachments,
  }), [
    assignments,
    activeCategoryTreeNodes,
    categorys,
    messages,
    newsroomSections,
    referenceAttachments,
    references,
    semanticNodes,
    semanticRelations,
  ]);

  const categoryByUid = useMemo(() => {
    const map = new Map<string, CategorySteeringCategory>();
    for (const category of categorys) map.set(category.categoryKey, category);
    return map;
  }, [categorys]);
  const initialSearchRequest = useMemo(() => parseNewsroomSearchRequest(initialSelection), [initialSelection]);
  const topBarSearchControl = useNewsroomRouteSearch({
    activeTab,
    assignments,
    categorys,
    dashboard,
    disabled: Boolean(dashboard.isDemo),
    initialRequest: initialSearchRequest,
    messages,
    newsroomSections,
    references,
    semanticNodes,
  });
  const canRefreshNewsroomSections = canEdit && editorShellReady && authState.status === "signedIn" && !dashboard.isDemo;
  const refreshNewsroomSections = useCallback(async () => {
    if (dashboard.isDemo || !canRefreshNewsroomSections) {
      setNewsroomSections(fallbackNewsroomSections);
      return;
    }
    const nextSections = await listNewsroomSectionsFromApi(dataClient);
    setNewsroomSections((current) => {
      const mergedNextSections = normalizeNewsroomSectionsWithFallback(
        nextSections,
        current.length > 0 ? current : fallbackNewsroomSections,
      );
      return mergedNextSections.length === 0 && current.length > 0 ? current : mergedNextSections;
    });
  }, [canRefreshNewsroomSections, dashboard.isDemo, fallbackNewsroomSections, dataClient]);

  useEffect(() => {
    setCorpora(dashboard.corpora);
  }, [dashboard.corpora]);

  useEffect(() => {
    setImportRuns(dashboard.importRuns);
  }, [dashboard.importRuns]);

  useEffect(() => {
    setCategorySets(dashboard.categorySets);
  }, [dashboard.categorySets]);

  useEffect(() => {
    setArtifacts(dashboard.artifacts);
  }, [dashboard.artifacts]);

  useEffect(() => {
    setCanonicalCorpusId(dashboard.canonicalCorpusId ?? null);
  }, [dashboard.canonicalCorpusId]);

  useEffect(() => {
    setCanonicalCategorySetId(dashboard.canonicalCategorySetId ?? null);
  }, [dashboard.canonicalCategorySetId]);

  useEffect(() => {
    setCategorys(dashboard.categorys);
  }, [dashboard.categorys]);

  useEffect(() => {
    setCategoryKeywords(dashboard.categoryKeywords);
  }, [dashboard.categoryKeywords]);

  useEffect(() => {
    setLexicalSteeringRules(dashboard.lexicalSteeringRules);
  }, [dashboard.lexicalSteeringRules]);

  useEffect(() => {
    setProposals((current) => (
      dashboard.proposals.length === 0 && current.length > 0 ? current : dashboard.proposals
    ));
  }, [dashboard.proposals]);

  useEffect(() => {
    setSummary(dashboard.summary ?? null);
  }, [dashboard.summary]);

  useEffect(() => {
    setReferences(dashboard.references);
  }, [dashboard.references]);

  useEffect(() => {
    setReferenceAttachments(dashboard.referenceAttachments);
  }, [dashboard.referenceAttachments]);

  useEffect(() => {
    setMessages(dashboard.messages);
  }, [dashboard.messages]);

  useEffect(() => {
    setSemanticRelations(dashboard.semanticRelations);
  }, [dashboard.semanticRelations]);

  useEffect(() => {
    setSemanticNodes(dashboard.semanticNodes);
  }, [dashboard.semanticNodes]);

  useEffect(() => {
    setAssignments(dashboard.assignments);
    setAssignmentEvents(dashboard.assignmentEvents);
  }, [dashboard.assignments, dashboard.assignmentEvents]);

  useEffect(() => {
    setDoctrineRecords(dashboard.doctrineRecords);
    setDoctrineDrafts(buildDoctrineEditorState(dashboard.doctrineRecords));
  }, [dashboard.doctrineRecords]);

  useEffect(() => {
    setNewsroomSections((current) => normalizeNewsroomSectionsWithFallback(
      dashboard.newsroomSections,
      current.length > 0 ? current : undefined,
    ));
  }, [dashboard.newsroomSections]);

  useEffect(() => {
    setProcedureDefinitions(dashboard.procedureDefinitions ?? []);
    setProcedureVersions(dashboard.procedureVersions ?? []);
    setProcedureRuns(dashboard.procedureRuns ?? []);
  }, [dashboard.procedureDefinitions, dashboard.procedureRuns, dashboard.procedureVersions]);

  useEffect(() => {
    setAdministrationPanel(normalizeAdministrationPanel(initialSelection.panel));
  }, [initialSelection.panel]);

  useEffect(() => {
    if (activeTab !== "administration") return;
    if (administrationPanel !== "procedures") return;
    if (dashboard.isDemo || !dashboard.canManageUsers) return;
    if (procedureDefinitions.length > 0 && procedureVersions.length > 0) return;
    void refreshProcedureAdministrationData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeTab,
    administrationPanel,
    dashboard.canManageUsers,
    dashboard.isDemo,
    procedureDefinitions.length,
    procedureVersions.length,
  ]);

  useEffect(() => {
    setUserDirectory(dashboard.userDirectory);
  }, [dashboard.userDirectory]);

  useEffect(() => {
    setTaxonomies(dashboard.categoryTrees);
    setCategoryTreeNodes(dashboard.categoryNodes);
    setCategoryTreeLoadError(null);
  }, [dashboard.categoryNodes, dashboard.categoryTrees]);

  useEffect(() => {
    if (activeTab !== "topics" && activeTab !== "desks" && activeTab !== "concepts" && activeTab !== "administration") {
      return;
    }

    if (dashboard.isDemo) {
      setTaxonomies(dashboard.categoryTrees);
      setCategoryTreeNodes(dashboard.categoryNodes);
      setCategoryTreeLoadError(null);
      return;
    }

    let active = true;
    const refreshCategoryTree = async () => {
      const state = await loadEditorCategoryTreeState();
      if (!active) return;
      setTaxonomies(state.categoryTrees);
      setCategoryTreeNodes(state.categoryNodes);
      setCategorySets(state.categoryTrees);
      setCategorys(state.categoryNodes);
      const currentCategorySet = state.categoryTrees.find(isCurrentCategorySet) ?? null;
      setCanonicalCategorySetId(currentCategorySet?.id ?? null);
      setCategoryTreeLoadError(state.error);
    };

    void refreshCategoryTree();
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      if (
        payload.event === "signedIn" ||
        payload.event === "signedOut" ||
        payload.event === "signInWithRedirect" ||
        payload.event === "signInWithRedirect_failure"
      ) {
        void refreshCategoryTree();
      }
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [activeTab, dashboard.isDemo, dashboard.categoryTrees, dashboard.categoryNodes]);

  useEffect(() => {
    if (dashboard.isDemo) return;
    let active = true;

    if (activeTab === "messages" && !loadedSections.messages) {
      setLoadedSections((current) => ({ ...current, messages: true }));
      void loadEditorMessagesData()
        .then((nextMessages) => {
          if (active) setMessages(nextMessages);
        })
        .catch((error) => {
          if (active) setActionState({ id: "messages-load", message: error instanceof Error ? error.message : "messages load failed", tone: "error" });
        });
    }

    if (activeTab === "references" && !loadedSections.references) {
      setLoadedSections((current) => ({ ...current, references: true }));
      void loadEditorReferencesData()
        .then(({ references: nextReferences, referenceAttachments }) => {
          if (!active) return;
          setReferences(nextReferences);
          setReferenceAttachments(referenceAttachments);
          setHasHydratedReferences(true);
        })
        .catch((error) => {
          if (active) setActionState({ id: "references-load", message: error instanceof Error ? error.message : "references load failed", tone: "error" });
        });
    }

    if (activeTab === "assignments" && !loadedSections.assignments) {
      setLoadedSections((current) => ({ ...current, assignments: true }));
      void loadEditorAssignmentsData()
        .then((assignmentState) => {
          if (!active) return;
          setAssignments(assignmentState.assignments);
          setAssignmentEvents(assignmentState.assignmentEvents);
        })
        .catch((error) => {
          if (active) setActionState({ id: "assignments-load", message: error instanceof Error ? error.message : "assignments load failed", tone: "error" });
        });
    }

    if (
      canRefreshNewsroomSections
      && newsroomSections.length === 0
      && (activeTab === "administration" || activeTab === "overview" || isSectionPage)
      && !hasRefreshedNewsroomSections
    ) {
      setHasRefreshedNewsroomSections(true);
      setLoadedSections((current) => ({ ...current, sections: true }));
      void refreshNewsroomSections()
        .catch((error) => {
          if (active) setActionState({ id: "sections-load", message: error instanceof Error ? error.message : "sections load failed", tone: "error" });
        });
    }

    if ((activeTab === "assignments" || activeTab === "references" || activeTab === "messages") && !loadedSections.semanticRelations) {
      setLoadedSections((current) => ({ ...current, semanticRelations: true }));
      void loadEditorSemanticRelationsData()
        .then((relations) => {
          if (active) setSemanticRelations(relations);
        })
        .catch(() => {
          if (active) setSemanticRelations([]);
        });
      if (!loadedSections.messages) {
        setLoadedSections((current) => ({ ...current, messages: true }));
        void loadEditorMessagesData().then((nextMessages) => {
          if (active) setMessages(nextMessages);
        }).catch(() => undefined);
      }
    }

    if ((activeTab === "topics" || activeTab === "desks" || activeTab === "concepts" || activeTab === "administration") && !loadedSections.fullDashboard) {
      setLoadedSections((current) => ({ ...current, fullDashboard: true }));
      void loadEditorFullNewsDeskDashboard({ isAdmin: Boolean(dashboard.canManageUsers) })
        .then((nextDashboard) => {
          if (!active) return;
          setCorpora(nextDashboard.corpora);
          setImportRuns(nextDashboard.importRuns);
          setCategorySets(nextDashboard.categorySets);
          setArtifacts(nextDashboard.artifacts);
          setCanonicalCorpusId(nextDashboard.canonicalCorpusId ?? null);
          setCanonicalCategorySetId(nextDashboard.canonicalCategorySetId ?? null);
          setCategorys(nextDashboard.categorys);
          setTaxonomies(nextDashboard.categoryTrees);
          setCategoryTreeNodes(nextDashboard.categoryNodes);
          setCategoryKeywords(nextDashboard.categoryKeywords);
          setLexicalSteeringRules(nextDashboard.lexicalSteeringRules);
          setProposals(nextDashboard.proposals);
          setReferences(nextDashboard.references);
          setMessages(nextDashboard.messages);
          setSemanticRelations(nextDashboard.semanticRelations);
          setSemanticNodes(nextDashboard.semanticNodes);
          setAssignments(nextDashboard.assignments);
          setAssignmentEvents(nextDashboard.assignmentEvents);
          setDoctrineRecords(nextDashboard.doctrineRecords);
          setNewsroomSections((current) => normalizeNewsroomSectionsWithFallback(
            nextDashboard.newsroomSections,
            current.length > 0 ? current : fallbackNewsroomSections,
          ));
          setUserDirectory(nextDashboard.userDirectory);
        })
        .catch((error) => {
          if (active) setActionState({ id: "dashboard-load", message: error instanceof Error ? error.message : "Newsroom records load failed", tone: "error" });
        });
    }

    return () => {
      active = false;
    };
  }, [
    activeTab,
    dashboard.canManageUsers,
    dashboard.isDemo,
    newsroomSections.length,
    hasRefreshedNewsroomSections,
    canRefreshNewsroomSections,
    fallbackNewsroomSections,
    loadedSections.assignments,
    loadedSections.fullDashboard,
    loadedSections.messages,
    loadedSections.references,
    loadedSections.semanticRelations,
    isSectionPage,
    refreshNewsroomSections,
  ]);

  const applyReferenceRecord = useCallback((nextReference: ReferenceRecord) => {
    const { nextRecords, nextRecord, previousRecord } = upsertReferenceRecords(referencesRef.current, nextReference);
    referencesRef.current = nextRecords;
    setReferences(nextRecords);
    setSummary((current) => patchReferenceSummary(current, previousRecord, nextRecord));
    return { nextRecords, previousRecord };
  }, []);

  const hydrateReferenceFromRoute = useCallback((reference: ReferenceRecord) => {
    applyReferenceRecord(reference);
    const lineageId = reference.lineageId ?? reference.id;
    void loadReferenceAttachmentsForLineageId(lineageId)
      .then((attachments) => {
        if (!attachments.length) return;
        setReferenceAttachments((current) => {
          const next = current.filter((attachment) => attachment.referenceLineageId !== lineageId);
          next.push(...attachments);
          return next.sort((left, right) => left.sortKey.localeCompare(right.sortKey));
        });
      })
      .catch((error) => {
        console.error("[ReferencesDesk] Unable to load reference attachments for deep link", error);
      });
  }, [applyReferenceRecord]);

  useEffect(() => {
    if (dashboard.isDemo || activeTab !== "references" || authState.status !== "signedIn" || !hasHydratedReferences) {
      setReferencesRealtimeStatus("idle");
      setReferencesRealtimeError(null);
      return;
    }
    const referenceModel = referenceSubscriptionClient.models.Reference as unknown as ReferenceSubscriptionModel | undefined;
    const semanticRelationModel = referenceSubscriptionClient.models.SemanticRelation as unknown as SemanticRelationSubscriptionModel | undefined;
    if (!referenceModel || typeof referenceModel.onCreate !== "function" || typeof referenceModel.onUpdate !== "function") {
      setReferencesRealtimeStatus("error");
      setReferencesRealtimeError("Reference realtime model is unavailable.");
      return;
    }
    if (!semanticRelationModel || typeof semanticRelationModel.onCreate !== "function" || typeof semanticRelationModel.onUpdate !== "function") {
      setReferencesRealtimeStatus("error");
      setReferencesRealtimeError("Semantic relation realtime model is unavailable.");
      return;
    }

    let active = true;
    let reconnectAttempts = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let subscriptions: ReferenceSubscription[] = [];
    const referenceInput = { filter: { newsroomFeedKey: { eq: "references" } } };

    const clearSubscriptions = () => {
      for (const subscription of subscriptions) subscription.unsubscribe();
      subscriptions = [];
    };

    const scheduleReconnect = (error?: unknown) => {
      if (!active) return;
      clearSubscriptions();
      reconnectAttempts += 1;
      const delayMs = Math.min(30_000, 1000 * Math.max(1, 2 ** (reconnectAttempts - 1)));
      setReferencesRealtimeStatus(reconnectAttempts > 1 ? "stale" : "reconnecting");
      setReferencesRealtimeError(error instanceof Error ? error.message : "Realtime stream disconnected.");
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => {
        connect();
      }, delayMs);
    };

    const handleReferenceCreateOrUpdate = (value: unknown) => {
      const nextReference = normalizeReferenceSubscriptionPayload(value);
      if (!nextReference) return;
      applyReferenceRecord(nextReference);
    };

    const handleReferenceDelete = (value: unknown) => {
      const deletedReference = normalizeReferenceSubscriptionPayload(value);
      const deletedId = deletedReference?.id ?? extractSubscriptionRecordId(value);
      if (!deletedId) return;
      const previousRecord = referencesRef.current.find((entry) => entry.id === deletedId) ?? null;
      if (!previousRecord) return;
      const nextRecords = referencesRef.current.filter((entry) => entry.id !== deletedId);
      referencesRef.current = nextRecords;
      setReferences(nextRecords);
      setSummary((current) => patchReferenceSummaryForDelete(current, previousRecord));
    };

    const handleSemanticRelationCreateOrUpdate = (value: unknown) => {
      const relation = normalizeSemanticRelationSubscriptionPayload(value);
      if (!relation) return;
      setSemanticRelations((current) => upsertSemanticRelationRecords(current, relation));
    };

    const handleSemanticRelationDelete = (value: unknown) => {
      const relationId = extractSubscriptionRecordId(value);
      if (!relationId) return;
      setSemanticRelations((current) => current.filter((entry) => entry.id !== relationId));
    };

    const connect = () => {
      if (!active) return;
      clearSubscriptions();
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      setReferencesRealtimeStatus(reconnectAttempts > 0 ? "reconnecting" : "connecting");
      try {
        const nextSubscriptions: ReferenceSubscription[] = [
          referenceModel.onCreate(referenceInput).subscribe({ next: handleReferenceCreateOrUpdate, error: scheduleReconnect }),
          referenceModel.onUpdate(referenceInput).subscribe({ next: handleReferenceCreateOrUpdate, error: scheduleReconnect }),
          semanticRelationModel.onCreate().subscribe({ next: handleSemanticRelationCreateOrUpdate, error: scheduleReconnect }),
          semanticRelationModel.onUpdate().subscribe({ next: handleSemanticRelationCreateOrUpdate, error: scheduleReconnect }),
        ];
        if (typeof referenceModel.onDelete === "function") {
          nextSubscriptions.push(referenceModel.onDelete(referenceInput).subscribe({ next: handleReferenceDelete, error: scheduleReconnect }));
        }
        if (typeof semanticRelationModel.onDelete === "function") {
          nextSubscriptions.push(semanticRelationModel.onDelete().subscribe({ next: handleSemanticRelationDelete, error: scheduleReconnect }));
        }
        subscriptions = nextSubscriptions;
        reconnectAttempts = 0;
        setReferencesRealtimeStatus("connected");
        setReferencesRealtimeError(null);
      } catch (error) {
        scheduleReconnect(error);
      }
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearSubscriptions();
    };
  }, [
    activeTab,
    applyReferenceRecord,
    authState.status,
    dashboard.isDemo,
    hasHydratedReferences,
    referenceSubscriptionClient,
  ]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let isTestEditor = false;
    try {
      isTestEditor = window.localStorage.getItem("papyrus:test-editor") === "true";
    } catch {
      isTestEditor = false;
    }
    if (!isTestEditor) return;
    const handleTestReferenceUpdate = (event: Event) => {
      const nextReference = normalizeReferenceSubscriptionPayload((event as CustomEvent<unknown>).detail);
      if (!nextReference) return;
      applyReferenceRecord(nextReference);
    };
    window.addEventListener("papyrus:test-reference-update", handleTestReferenceUpdate);
    return () => {
      window.removeEventListener("papyrus:test-reference-update", handleTestReferenceUpdate);
    };
  }, [applyReferenceRecord]);

  function runProposalAction(proposal: CategorySteeringProposal, action: ReviewAction, input?: ProposalReviewInput) {
    const blockedReason = proposalReviewActionBlockedReason(proposal, action);
    if (blockedReason) {
      setActionState({ id: proposal.id, message: blockedReason, tone: "error" });
      return;
    }
    setActionState({ id: proposal.id, message: `${action} pending`, tone: "pending" });
    if (dashboard.isDemo) {
      const now = new Date().toISOString();
      setProposals((current) =>
        current.map((entry) =>
          entry.id === proposal.id
            ? {
                ...entry,
                status: action === "defer"
                  ? "deferred"
                  : action === "reject"
                    ? "rejected"
                    : "accepted",
                reviewedAt: now,
                displayName: input?.displayName ?? entry.displayName,
                shortTitle: input?.shortTitle ?? entry.shortTitle,
                subtitle: input?.subtitle ?? entry.subtitle,
                description: input?.description ?? entry.description,
              }
            : entry,
        ),
      );
      setActionState({ id: proposal.id, message: `${action} saved`, tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = await dataClient.mutations.reviewSteeringProposal(
            {
              proposalId: proposal.id,
              action,
              actorLabel: "Papyrus newsroom",
              note: input?.note ?? undefined,
              displayName: input?.displayName ?? proposal.displayName ?? undefined,
              shortTitle: input?.shortTitle ?? proposal.shortTitle ?? undefined,
              subtitle: input?.subtitle ?? proposal.subtitle ?? undefined,
              description: input?.description ?? proposal.description ?? undefined,
              aliases: input?.aliases ?? undefined,
              seedItemIds: input?.seedItemIds ?? compactArray(proposal.suggestedSeedItemIds),
              holdoutItemIds: input?.holdoutItemIds ?? compactArray(proposal.suggestedHoldoutItemIds),
            },
            { authMode: USER_POOL_AUTH_MODE },
          );
          const review = assertReviewMutationSucceeded(response, proposal.id);
          const nextStatus = review.status === "accepted" || review.status === "rejected" || review.status === "deferred"
            ? review.status
            : action === "defer"
              ? "deferred"
              : action === "reject"
                ? "rejected"
                : "accepted";
          setProposals((current) =>
            current.map((entry) =>
              entry.id === proposal.id
                ? {
                    ...entry,
                    status: nextStatus,
                    reviewedAt: new Date().toISOString(),
                    displayName: input?.displayName ?? entry.displayName,
                    shortTitle: input?.shortTitle ?? entry.shortTitle,
                    subtitle: input?.subtitle ?? entry.subtitle,
                    description: input?.description ?? entry.description,
                  }
                : entry,
            ),
          );
          if ((action === "accept" || action === "edit") && TAXONOMY_PROPOSAL_KINDS.has(proposal.proposalKind)) {
            await refreshEditorCategoryTreeState();
          }
          setActionState({ id: proposal.id, message: `${action} saved`, tone: "ok" });
        } catch (error) {
          setActionState({ id: proposal.id, message: error instanceof Error ? error.message : `${action} failed`, tone: "error" });
        }
      })();
    });
  }

  function runReferenceCurationAction(reference: ReferenceRecord, action: ReferenceCurationAction, note?: string, reasonCode?: ReferenceRejectionReasonCode | null) {
    const nextStatus = referenceCurationStatusForAction(action);
    setActionState({ id: reference.id, message: `${action} pending`, tone: "pending" });
    if (dashboard.isDemo) {
      const now = new Date().toISOString();
      const messageId = `message-demo-${reference.id}-${action}-${now.replace(/[^0-9]/g, "")}`;
      const relationId = `semantic-relation-demo-${messageId}`;
      applyReferenceRecord(buildReviewedReferenceRecord(referencesRef.current, reference, {
        actorLabel: authState.label,
        nextStatus,
        note: note ?? null,
        now,
      }));
      setMessages((current) => [{
        id: messageId,
        messageKind: "reference_curation",
        messageDomain: "commentary",
        status: "active",
        body: note?.trim() || `${authState.label} marked this reference ${nextStatus}.`,
        summary: `${reference.title ?? reference.externalItemId}: ${nextStatus}`,
        source: "newsroom",
        authorLabel: authState.label,
        createdAt: now,
        updatedAt: now,
        metadata: {
          action,
          curationStatus: nextStatus,
          reasonCode: action === "reject" ? reasonCode ?? null : null,
        },
      }, ...current]);
      setSemanticRelations((current) => [{
        id: relationId,
        relationState: "current",
        predicate: "comment",
        relationTypeId: "semantic-relation-type-comment",
        relationTypeKey: "comment",
        relationDomain: "commentary",
        subjectKind: "message",
        subjectId: messageId,
        subjectLineageId: messageId,
        subjectVersionNumber: 1,
        objectKind: "reference",
        objectId: reference.id,
        objectLineageId: reference.lineageId ?? reference.id,
        objectVersionNumber: reference.versionNumber ?? null,
        subjectStateKey: `message#${messageId}#current`,
        objectStateKey: `reference#${reference.lineageId ?? reference.id}#current`,
        objectSubjectStateKey: `reference#${reference.lineageId ?? reference.id}#current#message`,
        predicateObjectStateKey: `comment#reference#${reference.lineageId ?? reference.id}#current`,
        subjectVersionKey: `message#${messageId}`,
        objectVersionKey: `reference#${reference.id}`,
        rank: 1,
        reviewRecommended: false,
        importedAt: now,
      }, ...current]);
      setActionState({ id: reference.id, message: `${action} saved`, tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = await dataClient.mutations.reviewReferenceCuration(
            {
              referenceId: reference.id,
              action,
              actorLabel: authState.label,
              note: note?.trim() || undefined,
              reasonCode: action === "reject" ? reasonCode ?? undefined : undefined,
            },
            { authMode: USER_POOL_AUTH_MODE },
          );
          const review = assertReferenceReviewMutationSucceeded(response, reference.id);
          const status = review.status ?? nextStatus;
          const now = new Date().toISOString();
          applyReferenceRecord(buildReviewedReferenceRecord(referencesRef.current, reference, {
            actorLabel: authState.label,
            nextStatus: status,
            note: note?.trim() || null,
            now,
          }));
          setActionState({ id: reference.id, message: `${action} saved`, tone: "ok" });
        } catch (error) {
          setActionState({ id: reference.id, message: error instanceof Error ? error.message : `${action} failed`, tone: "error" });
        }
      })();
    });
  }

  function runReferenceQualityRating(reference: ReferenceRecord, rating: number) {
    const current = resolveReferenceCurationDisplayState(reference, graph);
    const nextStatus = rating >= 3 ? "accepted" : "rejected";
    if (
      (nextStatus === "accepted" && current.effectiveStatus === "accepted" && current.persistedQualityRating === rating)
      || (nextStatus === "rejected" && current.effectiveStatus === "rejected" && current.persistedQualityRating === null)
    ) {
      setReferenceQualityActionState(referenceQualityActionStateFromRating(
        reference.id,
        rating,
        "ok",
        `${rating}-star rating saved`,
      ));
      return;
    }
    setReferenceQualityActionState(referenceQualityActionStateFromRating(
      reference.id,
      rating,
      "pending",
      "Saving",
    ));
    setActionState({ id: `reference-quality-${reference.id}`, message: `${rating}-star rating pending`, tone: "pending" });
    const now = new Date().toISOString();
    if (shouldFailReferenceQualityMutationForTest()) {
      window.setTimeout(() => {
        const message = "Reference quality rating was not saved for test.";
        setReferenceQualityActionState(referenceQualityActionStateFromConfirmed(
          reference.id,
          rating,
          current,
          "error",
          message,
        ));
        setActionState({ id: `reference-quality-${reference.id}`, message, tone: "error" });
      }, 250);
      return;
    }
    if (dashboard.isDemo) {
      applyReferenceRecord(buildReviewedReferenceRecord(referencesRef.current, reference, {
        actorLabel: authState.label,
        nextStatus,
        note: null,
        now,
      }));
      setSemanticRelations((currentRelations) => upsertReferenceQualityRelations(
        currentRelations,
        reference,
        nextStatus === "accepted" ? rating : null,
        authState.label,
        now,
      ));
      setReferenceQualityActionState(referenceQualityActionStateFromRating(
        reference.id,
        rating,
        "ok",
        "Saved",
      ));
      setActionState({ id: `reference-quality-${reference.id}`, message: `${rating}-star rating saved`, tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = await dataClient.mutations.setReferenceQualityRating(
            {
              referenceId: reference.id,
              rating,
              actorLabel: authState.label,
            },
            { authMode: USER_POOL_AUTH_MODE },
          );
          const result = assertReferenceQualityMutationSucceeded(response as ReferenceQualityResponse, reference.id, rating);
          const savedStatus = result.status ?? nextStatus;
          applyReferenceRecord(buildReviewedReferenceRecord(referencesRef.current, reference, {
            actorLabel: authState.label,
            nextStatus: savedStatus,
            note: null,
            now,
          }));
          setSemanticRelations((currentRelations) => upsertReferenceQualityRelations(
            currentRelations,
            reference,
            savedStatus === "accepted" ? rating : null,
            authState.label,
            now,
            result.relationId ?? null,
          ));
          setReferenceQualityActionState(referenceQualityActionStateFromRating(
            reference.id,
            rating,
            "ok",
            "Saved",
          ));
          setActionState({ id: `reference-quality-${reference.id}`, message: `${rating}-star rating saved`, tone: "ok" });
        } catch (error) {
          setReferenceQualityActionState(referenceQualityActionStateFromConfirmed(
            reference.id,
            rating,
            current,
            "error",
            error instanceof Error ? error.message : "Quality rating failed",
          ));
          setActionState({
            id: `reference-quality-${reference.id}`,
            message: error instanceof Error ? error.message : "Quality rating failed",
            tone: "error",
          });
        }
      })();
    });
  }

  function runReferenceCorpusMove(reference: ReferenceRecord, corpusId: string) {
    if (!corpusId || corpusId === reference.corpusId) return;
    setActionState({ id: `reference-corpus-${reference.id}`, message: "corpus move pending", tone: "pending" });
    if (dashboard.isDemo) {
      applyReferenceRecord({
        ...reference,
        corpusId,
        updatedAt: new Date().toISOString(),
      });
      setActionState({ id: `reference-corpus-${reference.id}`, message: "corpus moved", tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = await dataClient.mutations.moveReferenceCorpus(
            {
              referenceId: reference.id,
              corpusId,
              actorLabel: authState.label,
              note: "Moved from newsroom reference detail.",
            },
            { authMode: USER_POOL_AUTH_MODE },
          );
          const moved = assertReferenceMoveCorpusMutationSucceeded(response as ReferenceCorpusMoveResponse, reference.id, corpusId);
          const movedReference = await loadReferenceRecordById(moved.referenceId ?? reference.id);
          if (movedReference) {
            applyReferenceRecord(movedReference);
          } else {
            applyReferenceRecord({
              ...reference,
              corpusId,
              updatedAt: new Date().toISOString(),
            });
          }
          setActionState({ id: `reference-corpus-${reference.id}`, message: "corpus moved", tone: "ok" });
        } catch (error) {
          setActionState({
            id: `reference-corpus-${reference.id}`,
            message: error instanceof Error ? error.message : "Corpus move failed",
            tone: "error",
          });
        }
      })();
    });
  }

  function runReferenceCurationStart(reference: ReferenceRecord) {
    const lineageId = reference.lineageId ?? reference.id;
    setActionState({ id: `reference-curation-${lineageId}`, message: "curation queued", tone: "pending" });
    if (dashboard.isDemo) {
      setReferenceCurationRunsByLineage((current) => ({
        ...current,
        [lineageId]: {
          assignmentId: `assignment-demo-curation-${safeUiId(lineageId)}`,
          status: "queued",
          lifecycleStatus: "queued",
          runId: `assignment-demo-curation-${safeUiId(lineageId)}`,
          stageStatuses: {},
          changedOutputs: {},
          error: null,
          updatedAt: new Date().toISOString(),
        },
      }));
      setActionState({ id: `reference-curation-${lineageId}`, message: "curation queued", tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = await dataClient.mutations.startReferenceCuration(
            {
              referenceId: reference.id,
              actorLabel: authState.label,
            },
            { authMode: USER_POOL_AUTH_MODE },
          );
          const started = assertReferenceCurationStartMutationSucceeded(response as ReferenceCurationStartResponse, reference.id);
          const assignmentId = started.assignmentId ?? "";
          if (!assignmentId) throw new Error("startReferenceCuration did not return assignmentId.");
          setReferenceCurationRunsByLineage((current) => ({
            ...current,
            [lineageId]: {
              assignmentId,
              status: started.status ?? "queued",
              lifecycleStatus: started.status ?? "queued",
              runId: started.runId ?? assignmentId,
              stageStatuses: {},
              changedOutputs: {},
              error: null,
              updatedAt: new Date().toISOString(),
            },
          }));
          for (let attempt = 0; attempt < 20; attempt += 1) {
            const statusResponse = await dataClient.queries.getReferenceCurationStatus(
              { assignmentId },
              { authMode: USER_POOL_AUTH_MODE },
            );
            const status = assertReferenceCurationStatusQuerySucceeded(statusResponse as ReferenceCurationStatusResponse, assignmentId);
            const lifecycle = status.lifecycleStatus ?? status.status ?? "queued";
            setReferenceCurationRunsByLineage((current) => ({
              ...current,
              [lineageId]: {
                assignmentId,
                status: status.status ?? lifecycle,
                lifecycleStatus: lifecycle,
                runId: status.runId ?? assignmentId,
                stageStatuses: status.stageStatuses ?? {},
                changedOutputs: status.changedOutputs ?? {},
                error: status.error ?? null,
                updatedAt: new Date().toISOString(),
              },
            }));
            if (["completed", "failed", "degraded"].includes(lifecycle)) break;
            await new Promise((resolve) => window.setTimeout(resolve, 1500));
          }
          setActionState({ id: `reference-curation-${lineageId}`, message: "curation status updated", tone: "ok" });
        } catch (error) {
          setActionState({
            id: `reference-curation-${lineageId}`,
            message: error instanceof Error ? error.message : "Start curation failed",
            tone: "error",
          });
        }
      })();
    });
  }

  async function createInsight(target: InsightTarget, summary: string, body: string): Promise<void> {
    const cleanSummary = summary.trim();
    const cleanBody = body.trim();
    if (!cleanSummary) throw new Error("Insight summary is required.");
    if (!cleanBody) throw new Error("Insight body is required.");
    const now = new Date().toISOString();
    const subjectSeed = [
      target.kind,
      target.lineageId,
      cleanSummary,
      cleanBody,
      now,
    ];
    const messageId = `message-insight-${safeUiId(target.kind)}-${safeUiId(target.lineageId)}-${hashUiKey(subjectSeed)}`;
    const message: MessageRecord = {
      id: messageId,
      messageKind: "insight",
      messageDomain: "knowledge",
      status: "active",
      summary: cleanSummary,
      source: "newsroom",
      authorLabel: authState.label,
      threadId: messageId,
      sequenceNumber: 1,
      createdAt: now,
      updatedAt: now,
      newsroomFeedKey: "messages",
      body: cleanBody,
      metadata: {
        targetKind: target.kind,
        targetId: target.id,
        targetLineageId: target.lineageId,
      },
    };
    const relation = buildUiInsightRelation(message, target, now);
    setActionState({ id: messageId, message: "insight pending", tone: "pending" });

    if (dashboard.isDemo) {
      setMessages((current) => [message, ...current.filter((entry) => entry.id !== message.id)]);
      setSemanticRelations((current) => [relation, ...current.filter((entry) => entry.id !== relation.id)]);
      setActionState({ id: messageId, message: "insight saved", tone: "ok" });
      return;
    }

    if (target.kind === "reference") {
      const response = await dataClient.mutations.createReferenceInsight(
        {
          referenceId: target.id,
          summary: cleanSummary,
          body: cleanBody,
          actorLabel: authState.label,
        },
        { authMode: USER_POOL_AUTH_MODE },
      );
      const created = assertReferenceInsightMutationSucceeded(response as ReferenceInsightResponse, target.id);
      const persistedMessageId = created.messageId ?? messageId;
      const persistedRelationId = created.relationId ?? relation.id;
      const persistedMessage: MessageRecord = {
        ...message,
        id: persistedMessageId,
      };
      const persistedRelation: SemanticRelationRecord = {
        ...relation,
        id: persistedRelationId,
        subjectId: persistedMessageId,
        subjectLineageId: persistedMessageId,
        subjectVersionKey: semanticVersionKey("message", persistedMessageId),
        subjectStateKey: semanticStateKey("message", persistedMessageId),
      };
      setMessages((current) => [persistedMessage, ...current.filter((entry) => entry.id !== persistedMessage.id)]);
      setSemanticRelations((current) => [persistedRelation, ...current.filter((entry) => entry.id !== persistedRelation.id)]);
      setActionState({ id: persistedMessageId, message: "insight saved", tone: "ok" });
      return;
    }

    if (!("Message" in dataClient.models)) throw new Error("GraphQL model Message is not available in the deployed schema.");
    if (!("SemanticRelation" in dataClient.models)) throw new Error("GraphQL model SemanticRelation is not available in the deployed schema.");

    const messageInput = {
      id: message.id,
      messageKind: message.messageKind,
      messageDomain: message.messageDomain,
      status: message.status,
      summary: message.summary,
      source: message.source,
      authorLabel: message.authorLabel,
      threadId: message.id,
      sequenceNumber: 1,
      createdAt: message.createdAt,
      updatedAt: message.updatedAt,
      newsroomFeedKey: "messages",
    };
    const messageResponse = await dataClient.models.Message.create(messageInput as never, { authMode: USER_POOL_AUTH_MODE });
    assertNoGraphQLErrors(messageResponse.errors);
    await uploadModelPayloadForOwner({
      ownerKind: "message",
      ownerId: messageId,
      ownerLineageId: messageId,
      role: "message_body",
      sortKey: "message",
      filename: "message.md",
      mediaType: "text/markdown",
      content: cleanBody.endsWith("\n") ? cleanBody : `${cleanBody}\n`,
      status: "active",
    });
    const relationResponse = await dataClient.models.SemanticRelation.create(relation as never, { authMode: USER_POOL_AUTH_MODE });
    assertNoGraphQLErrors(relationResponse.errors);
    setMessages((current) => [message, ...current.filter((entry) => entry.id !== message.id)]);
    setSemanticRelations((current) => [relation, ...current.filter((entry) => entry.id !== relation.id)]);
    setActionState({ id: messageId, message: "insight saved", tone: "ok" });
  }

  function createLexicalSteeringRule(draft: LexicalRuleDraft) {
    const normalizedTerm = normalizeKeywordTerm(draft.term);
    if (!normalizedTerm) {
      setActionState({ id: "lexical-rule-empty", message: "keyword term is required", tone: "error" });
      return;
    }
    const now = new Date().toISOString();
    const rule: LexicalSteeringRuleRecord = {
      id: `lexical-rule-ignored-keyword-${hashUiKey([
        draft.scope,
        draft.corpusId ?? "",
        draft.classifierId ?? "",
        draft.categorySetId ?? "",
        draft.categoryKey ?? "",
        normalizedTerm,
      ])}`,
      ruleKind: "ignored_keyword",
      term: draft.term.trim(),
      normalizedTerm,
      scope: draft.scope,
      status: "active",
      corpusId: draft.corpusId ?? null,
      classifierId: draft.classifierId ?? null,
      categorySetId: draft.categorySetId ?? null,
      categoryKey: draft.categoryKey ?? null,
      note: draft.note ?? null,
      source: "newsroom",
      createdBy: authState.label,
      createdAt: now,
      updatedAt: now,
      metadata: { createdFrom: "newsroom/topics" },
    };
    setActionState({ id: rule.id, message: "ignore rule pending", tone: "pending" });
    if (dashboard.isDemo) {
      setLexicalSteeringRules((current) => upsertLocalLexicalRule(current, rule));
      setActionState({ id: rule.id, message: `ignoring "${rule.term}"`, tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          if (!("LexicalSteeringRule" in dataClient.models)) {
            throw new Error("GraphQL model LexicalSteeringRule is not available in the deployed schema.");
          }
          const response = await dataClient.models.LexicalSteeringRule.create(rule as never, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(response.errors);
          setLexicalSteeringRules((current) => upsertLocalLexicalRule(current, rule));
          setActionState({ id: rule.id, message: `ignoring "${rule.term}"`, tone: "ok" });
        } catch (error) {
          setActionState({ id: rule.id, message: error instanceof Error ? error.message : "ignore rule failed", tone: "error" });
        }
      })();
    });
  }

  function runAssignmentAction(assignment: AssignmentRecord, action: AssignmentAction, note = "") {
    setActionState({ id: assignment.id, message: `${action} pending`, tone: "pending" });
    if (dashboard.isDemo) {
      const now = new Date().toISOString();
      setAssignments((current) => current.map((entry) => entry.id === assignment.id ? applyAssignmentActionLocally(entry, action, now) : entry));
      setAssignmentEvents((current) => [demoAssignmentEvent(assignment, action, now, note), ...current]);
      setActionState({ id: assignment.id, message: `${action} saved`, tone: "ok" });
      return;
    }

    startTransition(() => {
      void (async () => {
        try {
          const actorLabel = await getNewsDeskActorLabel();
          await executeAssignmentAction(assignment.id, action, actorLabel, note);
          await refreshEditorAssignments();
          setActionState({ id: assignment.id, message: `${action} saved`, tone: "ok" });
        } catch (error) {
          setActionState({
            id: assignment.id,
            message: error instanceof Error ? error.message : `${action} failed`,
            tone: "error",
          });
          await refreshEditorAssignments();
        }
      })();
    });
  }

  function runReportingPacketReview(assignment: AssignmentRecord, packet: AssignmentResearchPacketSummary, decision: ReportingPacketReviewDecision, note = "", targetItemId = "") {
    const actionId = `${assignment.id}:${decision}`;
    setActionState({ id: actionId, message: `reporting ${decision} pending`, tone: "pending" });
    const message = messages.find((entry) => entry.id === packet.id);
    if (!message) {
      setActionState({ id: actionId, message: "reporting packet message missing", tone: "error" });
      return;
    }
    const now = new Date().toISOString();
    if (dashboard.isDemo) {
      try {
        const plan = buildUiReportingPacketReviewPlan({
          actorLabel: "Papyrus newsroom",
          assignment,
          decision,
          message,
          note,
          now,
          targetItemId,
        });
        setAssignmentEvents((current) => [plan.event, ...current.filter((entry) => entry.id !== plan.event.id)]);
        if (plan.copywritingAssignment) {
          const copywritingAssignment = plan.copywritingAssignment;
          setAssignments((current) => [copywritingAssignment, ...current.filter((entry) => entry.id !== copywritingAssignment.id)]);
        }
        if (plan.relations.length) {
          setSemanticRelations((current) => [
            ...plan.relations,
            ...current.filter((entry) => !plan.relations.some((relation) => relation.id === entry.id)),
          ]);
        }
        setActionState({ id: actionId, message: `reporting ${decision} saved`, tone: "ok" });
      } catch (error) {
        setActionState({ id: actionId, message: error instanceof Error ? error.message : `reporting ${decision} failed`, tone: "error" });
      }
      return;
    }

    startTransition(() => {
      void (async () => {
        try {
          const actorLabel = await getNewsDeskActorLabel();
          const targetItem = targetItemId.trim()
            ? await fetchUiItemForReportingMerge(targetItemId.trim())
            : null;
          const plan = buildUiReportingPacketReviewPlan({
            actorLabel,
            assignment,
            decision,
            message,
            note,
            now,
            targetItem,
            targetItemId,
          });
          if (!("AssignmentEvent" in dataClient.models)) throw new Error("GraphQL model AssignmentEvent is not available in the deployed schema.");
          if (plan.copywritingAssignment) {
            if (!("Assignment" in dataClient.models)) throw new Error("GraphQL model Assignment is not available in the deployed schema.");
            const assignmentInput = { ...plan.copywritingAssignment };
            const assignmentBrief = assignmentInput.brief;
            const assignmentInstructions = assignmentInput.instructions;
            const assignmentMetadata = assignmentInput.metadata;
            delete assignmentInput.brief;
            delete assignmentInput.instructions;
            delete assignmentInput.metadata;
            const assignmentResponse = await dataClient.models.Assignment.create(assignmentInput as never, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(assignmentResponse.errors);
            if (assignmentBrief != null) {
              await uploadModelPayloadForOwner({
                ownerKind: "assignment",
                ownerId: plan.copywritingAssignment.id,
                ownerLineageId: plan.copywritingAssignment.id,
                role: "assignment_brief",
                sortKey: "brief",
                filename: "brief.txt",
                mediaType: "text/plain",
                content: String(assignmentBrief),
                status: "active",
              });
            }
            if (assignmentInstructions != null) {
              await uploadModelPayloadForOwner({
                ownerKind: "assignment",
                ownerId: plan.copywritingAssignment.id,
                ownerLineageId: plan.copywritingAssignment.id,
                role: "assignment_instructions",
                sortKey: "instructions",
                filename: "instructions.txt",
                mediaType: "text/plain",
                content: String(assignmentInstructions),
                status: "active",
              });
            }
            if (assignmentMetadata != null) {
              await uploadModelPayloadForOwner({
                ownerKind: "assignment",
                ownerId: plan.copywritingAssignment.id,
                ownerLineageId: plan.copywritingAssignment.id,
                role: "metadata",
                sortKey: "metadata",
                filename: "metadata.json",
                mediaType: "application/json",
                content: JSON.stringify(assignmentMetadata, null, 2),
                status: "active",
              });
            }
          }
          if (plan.relations.length) {
            if (!("SemanticRelation" in dataClient.models)) throw new Error("GraphQL model SemanticRelation is not available in the deployed schema.");
            for (const relation of plan.relations) {
              const relationResponse = await dataClient.models.SemanticRelation.create(relation as never, { authMode: USER_POOL_AUTH_MODE });
              assertNoGraphQLErrors(relationResponse.errors);
            }
          }
          const eventInput = { ...plan.event };
          delete eventInput.metadata;
          const eventResponse = await dataClient.models.AssignmentEvent.create(eventInput as never, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(eventResponse.errors);
          await uploadModelPayloadForOwner({
            ownerKind: "assignmentEvent",
            ownerId: plan.event.id,
            ownerLineageId: plan.event.id,
            role: "metadata",
            sortKey: "metadata",
            filename: "metadata.json",
            mediaType: "application/json",
            content: JSON.stringify(plan.event.metadata ?? {}, null, 2),
            status: "active",
          });
          setAssignmentEvents((current) => [plan.event, ...current.filter((entry) => entry.id !== plan.event.id)]);
          if (plan.copywritingAssignment) {
            const copywritingAssignment = plan.copywritingAssignment;
            setAssignments((current) => [copywritingAssignment, ...current.filter((entry) => entry.id !== copywritingAssignment.id)]);
          }
          if (plan.relations.length) {
            setSemanticRelations((current) => [
              ...plan.relations,
              ...current.filter((entry) => !plan.relations.some((relation) => relation.id === entry.id)),
            ]);
          }
          setActionState({ id: actionId, message: `reporting ${decision} saved`, tone: "ok" });
        } catch (error) {
          setActionState({ id: actionId, message: error instanceof Error ? error.message : `reporting ${decision} failed`, tone: "error" });
          await refreshEditorAssignments();
        }
      })();
    });
  }

  async function fetchUiItemForReportingMerge(itemId: string): Promise<UiReportingReviewItemTarget> {
    if (!("Item" in dataClient.models)) throw new Error("GraphQL model Item is not available in the deployed schema.");
    const model = dataClient.models.Item as unknown as {
      get: (input: { id: string }, options: { authMode: typeof USER_POOL_AUTH_MODE }) => Promise<{ data?: UiReportingReviewItemTarget | null; errors?: unknown[] | null }>;
    };
    const response = await model.get({ id: itemId }, { authMode: USER_POOL_AUTH_MODE });
    assertNoGraphQLErrors(response.errors);
    if (!response.data?.id) throw new Error(`Target Item ${itemId} was not found.`);
    return response.data;
  }

  function createAnalysisReindexAssignment(profile: AnalysisProfileSummary, draft: AnalysisReindexDraft) {
    const now = new Date().toISOString();
    const actorLabel = dashboard.isDemo ? "Papyrus newsroom" : authState.label || "Papyrus newsroom";
    const plan = buildUiAnalysisReindexAssignmentPlan({
      actorLabel,
      categorySet: activeCategorySet,
      corpora,
      draft,
      now,
      profile,
    });
    setActionState({ id: plan.assignment.id, message: "re-index assignment pending", tone: "pending" });

    if (dashboard.isDemo) {
      setAssignments((current) => [plan.assignment, ...current.filter((entry) => entry.id !== plan.assignment.id)]);
      setAssignmentEvents((current) => [plan.event, ...current.filter((entry) => entry.id !== plan.event.id)]);
      if (plan.relation) {
        const relation = plan.relation;
        setSemanticRelations((current) => [relation, ...current.filter((entry) => entry.id !== relation.id)]);
      }
      setActionState({ id: plan.assignment.id, message: "re-index assignment created", tone: "ok" });
      return;
    }

    startTransition(() => {
      void (async () => {
        try {
          const liveActorLabel = await getNewsDeskActorLabel();
          const livePlan = buildUiAnalysisReindexAssignmentPlan({
            actorLabel: liveActorLabel,
            categorySet: activeCategorySet,
            corpora,
            draft,
            now,
            profile,
          });
          if (!("Assignment" in dataClient.models)) throw new Error("GraphQL model Assignment is not available in the deployed schema.");
          if (!("AssignmentEvent" in dataClient.models)) throw new Error("GraphQL model AssignmentEvent is not available in the deployed schema.");
          const assignmentResponse = await dataClient.models.Assignment.create(livePlan.assignment as never, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(assignmentResponse.errors);
          const eventResponse = await dataClient.models.AssignmentEvent.create(livePlan.event as never, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(eventResponse.errors);
          if (livePlan.relation) {
            const relation = livePlan.relation;
            if (!("SemanticRelation" in dataClient.models)) throw new Error("GraphQL model SemanticRelation is not available in the deployed schema.");
            const relationResponse = await dataClient.models.SemanticRelation.create(relation as never, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(relationResponse.errors);
            setSemanticRelations((current) => [relation, ...current.filter((entry) => entry.id !== relation.id)]);
          }
          await refreshEditorAssignments();
          setActionState({ id: livePlan.assignment.id, message: "re-index assignment created", tone: "ok" });
        } catch (error) {
          setActionState({ id: plan.assignment.id, message: error instanceof Error ? error.message : "re-index assignment failed", tone: "error" });
          await refreshEditorAssignments();
        }
      })();
    });
  }

  async function refreshEditorAssignments() {
    if (dashboard.isDemo) {
      setAssignments(dashboard.assignments);
      setAssignmentEvents(dashboard.assignmentEvents);
      return;
    }
    if (onRefreshAssignments) {
      await onRefreshAssignments();
      return;
    }
    const state = await loadEditorAssignmentsData();
    setAssignments(state.assignments);
    setAssignmentEvents(state.assignmentEvents);
  }

  async function refreshEditorUserDirectory() {
    if (dashboard.isDemo) {
      setUserDirectory(dashboard.userDirectory);
      return;
    }
    if (onRefreshUserDirectory) {
      await onRefreshUserDirectory();
      return;
    }
    setUserDirectory(await loadEditorUserDirectoryData());
  }

  async function refreshEditorDoctrineRecords() {
    if (dashboard.isDemo) {
      setDoctrineRecords(dashboard.doctrineRecords);
      setDoctrineDrafts(buildDoctrineEditorState(dashboard.doctrineRecords));
      return;
    }
    if (onRefreshDoctrineRecords) {
      await onRefreshDoctrineRecords();
      return;
    }
    const nextRecords = await loadEditorDoctrineRecordsData({ doctrineCategories: acceptedDoctrineCategories });
    setDoctrineRecords(nextRecords);
    setDoctrineDrafts(buildDoctrineEditorState(nextRecords));
  }

  async function refreshEditorCategoryTreeState() {
    if (dashboard.isDemo) {
      setTaxonomies(dashboard.categoryTrees);
      setCategoryTreeNodes(dashboard.categoryNodes);
      setCategoryTreeLoadError(null);
      return;
    }
    const state = await loadEditorCategoryTreeState();
    setTaxonomies(state.categoryTrees);
    setCategoryTreeNodes(state.categoryNodes);
    setCategorySets(state.categoryTrees);
    setCategorys(state.categoryNodes);
    const currentCategorySet = state.categoryTrees.find(isCurrentCategorySet) ?? null;
    setCanonicalCategorySetId(currentCategorySet?.id ?? null);
    setCategoryTreeLoadError(state.error);
  }

  async function refreshEditorFullDashboard() {
    if (dashboard.isDemo) return;
    const nextDashboard = await loadEditorFullNewsDeskDashboard({ isAdmin: Boolean(dashboard.canManageUsers) });
    setCorpora(nextDashboard.corpora);
    setImportRuns(nextDashboard.importRuns);
    setCategorySets(nextDashboard.categorySets);
    setArtifacts(nextDashboard.artifacts);
    setCanonicalCorpusId(nextDashboard.canonicalCorpusId ?? null);
    setCanonicalCategorySetId(nextDashboard.canonicalCategorySetId ?? null);
    setCategorys(nextDashboard.categorys);
    setTaxonomies(nextDashboard.categoryTrees);
    setCategoryTreeNodes(nextDashboard.categoryNodes);
    setCategoryTreeLoadError(null);
    setCategoryKeywords(nextDashboard.categoryKeywords);
    setLexicalSteeringRules(nextDashboard.lexicalSteeringRules);
    setProposals(nextDashboard.proposals);
    setReferences(nextDashboard.references);
    setReferenceAttachments(nextDashboard.referenceAttachments);
    setMessages(nextDashboard.messages);
    setSemanticRelations(nextDashboard.semanticRelations);
    setSemanticNodes(nextDashboard.semanticNodes);
    setAssignments(nextDashboard.assignments);
    setAssignmentEvents(nextDashboard.assignmentEvents);
    setEditionSlots(nextDashboard.editionSlots ?? []);
    setDoctrineRecords(nextDashboard.doctrineRecords);
    setNewsroomSections(sortNewsroomSections(nextDashboard.newsroomSections));
    setUserDirectory(nextDashboard.userDirectory);
  }

  function updateDoctrineDraft(kind: DoctrineKind, text: string) {
    setDoctrineDrafts((current) => ({ ...current, [kind]: text }));
  }

  function saveDoctrine(kind: DoctrineKind) {
    const definition = requireDoctrineDefinition(kind);
    const currentRecord = doctrineRecords.find((record) => record.slug === definition.slug) ?? null;
    const recordKey = definition.slug;
    setActionState({ id: recordKey, message: "doctrine save pending", tone: "pending" });

    const nextBody = doctrineTextToBody(doctrineDrafts[kind]);
    const now = new Date().toISOString();

    if (dashboard.isDemo) {
      const nextRecord = buildDoctrineRecord(kind, nextBody, currentRecord, now, "Papyrus newsroom");
      setDoctrineRecords((current) => replaceDoctrineRecord(current, nextRecord));
      setActionState({ id: recordKey, message: "doctrine saved", tone: "ok" });
      return;
    }

    startTransition(() => {
      void (async () => {
        try {
          const actorLabel = await getNewsDeskActorLabel();
          const nextRecord = buildDoctrineRecord(kind, nextBody, currentRecord, now, actorLabel);
          if (currentRecord) {
            const response = await dataClient.models.Item.update({
              id: currentRecord.id,
              title: nextRecord.title,
              headline: nextRecord.headline,
              body: nextRecord.body,
              editorial: nextRecord.editorial,
              updatedAt: nextRecord.updatedAt,
            }, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(response.errors);
            if (!response.data?.id) throw new Error("Doctrine update returned no saved record.");
          } else {
            const response = await dataClient.models.Item.create(nextRecord as never, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(response.errors);
            if (!response.data?.id) throw new Error("Doctrine create returned no saved record.");
          }
          await refreshEditorDoctrineRecords();
          setActionState({ id: recordKey, message: "doctrine saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: recordKey, message: error instanceof Error ? error.message : "doctrine save failed", tone: "error" });
          await refreshEditorDoctrineRecords();
        }
      })();
    });
  }

  function saveCategoryDoctrine(category: DoctrineCategory, kind: DoctrineKind, text: string) {
    const definition = buildCategoryDoctrineDefinition(category, kind);
    const currentRecord = doctrineRecords.find((record) => record.slug === definition.slug) ?? null;
    const recordKey = definition.slug;
    setActionState({ id: recordKey, message: "category doctrine save pending", tone: "pending" });

    const nextBody = doctrineTextToBody(text);
    const now = new Date().toISOString();

    if (dashboard.isDemo) {
      const nextRecord = buildCategoryDoctrineRecord(category, kind, nextBody, currentRecord, now, "Papyrus newsroom");
      setDoctrineRecords((current) => replaceDoctrineRecord(current, nextRecord));
      setActionState({ id: recordKey, message: "category doctrine saved", tone: "ok" });
      return;
    }

    startTransition(() => {
      void (async () => {
        try {
          const actorLabel = await getNewsDeskActorLabel();
          const nextRecord = buildCategoryDoctrineRecord(category, kind, nextBody, currentRecord, now, actorLabel);
          if (currentRecord) {
            const response = await dataClient.models.Item.update({
              id: currentRecord.id,
              title: nextRecord.title,
              headline: nextRecord.headline,
              body: nextRecord.body,
              editorial: nextRecord.editorial,
              updatedAt: nextRecord.updatedAt,
            }, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(response.errors);
            if (!response.data?.id) throw new Error("Category doctrine update returned no saved record.");
          } else {
            const response = await dataClient.models.Item.create(nextRecord as never, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(response.errors);
            if (!response.data?.id) throw new Error("Category doctrine create returned no saved record.");
          }
          await refreshEditorDoctrineRecords();
          setActionState({ id: recordKey, message: "category doctrine saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: recordKey, message: error instanceof Error ? error.message : "category doctrine save failed", tone: "error" });
          await refreshEditorDoctrineRecords();
        }
      })();
    });
  }

  function runSectionUpsert(input: NewsroomSectionRecord, existingId?: string) {
    const sectionId = existingId ?? input.id;
    setActionState({ id: `section-${sectionId}`, message: "section save pending", tone: "pending" });
    const now = new Date().toISOString();
    const record = {
      ...input,
      id: sectionId,
      updatedAt: now,
      createdAt: input.createdAt ?? now,
    };
    if (dashboard.isDemo) {
      setNewsroomSections((current) => sortNewsroomSections(replaceNewsroomSection(current, record)));
      setActionState({ id: `section-${sectionId}`, message: "section saved", tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = existingId
            ? await dataClient.models.NewsroomSection.update(record as never, { authMode: USER_POOL_AUTH_MODE })
            : await dataClient.models.NewsroomSection.create(record as never, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(response.errors);
          if (!response.data?.id) throw new Error("Section save returned no record id.");
          await refreshNewsroomSections();
          setActionState({ id: `section-${sectionId}`, message: "section saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: `section-${sectionId}`, message: error instanceof Error ? error.message : "section save failed", tone: "error" });
          await refreshNewsroomSections();
        }
      })();
    });
  }

  function runSectionReorder(nextOrder: NewsroomSectionRecord[]) {
    const ordered = nextOrder.map((entry, index) => ({ ...entry, sortOrder: index + 1 }));
    setActionState({ id: "sections-reorder", message: "section reorder pending", tone: "pending" });
    if (dashboard.isDemo) {
      setNewsroomSections(sortNewsroomSections(ordered));
      setActionState({ id: "sections-reorder", message: "section order saved", tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          for (const section of ordered) {
            const response = await dataClient.models.NewsroomSection.update({
              id: section.id,
              sortOrder: section.sortOrder,
              updatedAt: new Date().toISOString(),
            } as never, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(response.errors);
          }
          await refreshNewsroomSections();
          setActionState({ id: "sections-reorder", message: "section order saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: "sections-reorder", message: error instanceof Error ? error.message : "section order save failed", tone: "error" });
          await refreshNewsroomSections();
        }
      })();
    });
  }

  async function refreshProcedureAdministrationData() {
    if (dashboard.isDemo) return;
    if (!dashboard.canManageUsers) return;
    const payload = await loadEditorProcedureData();
    setProcedureDefinitions(payload.definitions);
    setProcedureVersions(payload.versions);
    setProcedureRuns(payload.runs);
  }

  function runProcedureDefinitionSave(input: {
    id?: string;
    procedureKey: string;
    title: string;
    category: string;
    description?: string;
    enabled: boolean;
  }) {
    const recordKey = `procedure-definition-${input.procedureKey}`;
    setActionState({ id: recordKey, message: "procedure save pending", tone: "pending" });
    if (dashboard.isDemo) {
      setActionState({ id: recordKey, message: "procedure saved (demo)", tone: "ok" });
      return;
    }
    if (!dashboard.canManageUsers) {
      setActionState({ id: recordKey, message: "admin role required", tone: "error" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          await saveProcedureDefinitionRecord(input);
          await refreshProcedureAdministrationData();
          setActionState({ id: recordKey, message: "procedure saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: recordKey, message: error instanceof Error ? error.message : "procedure save failed", tone: "error" });
        }
      })();
    });
  }

  function runProcedureVersionDraftSave(input: {
    id?: string;
    procedureId: string;
    procedureKey?: string;
    label?: string;
    tactusSource: string;
    parameterSchema: Record<string, unknown>;
    defaults?: Record<string, unknown>;
    changelog?: string;
  }) {
    const recordKey = `procedure-version-${input.procedureId}`;
    setActionState({ id: recordKey, message: "procedure draft save pending", tone: "pending" });
    if (dashboard.isDemo) {
      setActionState({ id: recordKey, message: "procedure draft saved (demo)", tone: "ok" });
      return;
    }
    if (!dashboard.canManageUsers) {
      setActionState({ id: recordKey, message: "admin role required", tone: "error" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          await saveProcedureVersionDraftRecord(input);
          await refreshProcedureAdministrationData();
          setActionState({ id: recordKey, message: "procedure draft saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: recordKey, message: error instanceof Error ? error.message : "procedure draft save failed", tone: "error" });
        }
      })();
    });
  }

  function runProcedureVersionPublish(versionId: string) {
    const recordKey = `procedure-publish-${versionId}`;
    setActionState({ id: recordKey, message: "publish pending", tone: "pending" });
    if (dashboard.isDemo) {
      setActionState({ id: recordKey, message: "published (demo)", tone: "ok" });
      return;
    }
    if (!dashboard.canManageUsers) {
      setActionState({ id: recordKey, message: "admin role required", tone: "error" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          await publishProcedureVersionRecord(versionId);
          await refreshProcedureAdministrationData();
          setActionState({ id: recordKey, message: "published", tone: "ok" });
        } catch (error) {
          setActionState({ id: recordKey, message: error instanceof Error ? error.message : "publish failed", tone: "error" });
        }
      })();
    });
  }

  function runProcedureNow(input: {
    procedureId?: string;
    procedureKey?: string;
    procedureVersionId?: string;
    title?: string;
    summary?: string;
    parameters?: Record<string, unknown>;
  }) {
    const key = `procedure-run-${input.procedureKey ?? input.procedureId ?? "unknown"}`;
    setActionState({ id: key, message: "procedure run pending", tone: "pending" });
    if (dashboard.isDemo) {
      setActionState({ id: key, message: "procedure run queued (demo)", tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          await startProcedureRunRecord({ ...input, actorLabel: authState.label });
          if (dashboard.canManageUsers) await refreshProcedureAdministrationData();
          const nextDashboard = await loadEditorFullNewsDeskDashboard({ isAdmin: Boolean(dashboard.canManageUsers) });
          setAssignments(nextDashboard.assignments);
          setAssignmentEvents(nextDashboard.assignmentEvents);
          setActionState({ id: key, message: "procedure run dispatched", tone: "ok" });
        } catch (error) {
          setActionState({ id: key, message: error instanceof Error ? error.message : "procedure run failed", tone: "error" });
        }
      })();
    });
  }

  async function executeAssignmentAction(assignmentId: string, action: AssignmentAction, actorLabel: string, note: string) {
    const mutationName = (action === "retry" ? "retryImmediateAssignment" : `${action}Assignment`) as keyof typeof dataClient.mutations;
    const mutation = dataClient.mutations[mutationName] as unknown as ((args: Record<string, unknown>, options: { authMode: typeof USER_POOL_AUTH_MODE }) => Promise<unknown>) | undefined;
    if (!mutation) throw new Error(`Assignment action ${mutationName} is not available in the deployed schema.`);
    await mutation({
      assignmentId,
      actorLabel,
      assigneeType: "user",
      assigneeId: actorLabel,
      note: note.trim() || undefined,
    }, { authMode: USER_POOL_AUTH_MODE });
  }

  function runUserRoleAction(user: UserDirectoryEntry, role: string, action: UserRoleAction) {
    const userId = user.userProfileId ?? user.userSub ?? "unknown-user";
    const label = action === "grant" ? "grant" : "revoke";
    setActionState({ id: userId, message: `${label} ${role} pending`, tone: "pending" });
    if (dashboard.isDemo) {
      setUserDirectory((current) => current.map((entry) => {
        if ((entry.userProfileId ?? entry.userSub) !== (user.userProfileId ?? user.userSub)) return entry;
        const roles = new Set(compactArray(entry.activeRoles));
        if (action === "grant") roles.add(role);
        if (action === "revoke") roles.delete(role);
        return { ...entry, activeRoles: Array.from(roles).sort() };
      }));
      setActionState({ id: userId, message: `${label} ${role} saved`, tone: "ok" });
      return;
    }
    if (!dashboard.canManageUsers) {
      setActionState({ id: userId, message: "admin role required", tone: "error" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const input = {
            userProfileId: user.userProfileId ?? undefined,
            userSub: user.userSub ?? undefined,
            cognitoSubs: compactArray(user.identities?.map((identity) => identity.cognitoSub) ?? []),
            role,
          };
          const response = action === "grant"
            ? await dataClient.mutations.grantUserRole(input, { authMode: USER_POOL_AUTH_MODE })
            : await dataClient.mutations.revokeUserRole(input, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(response.errors);
          const activeRoles = compactArray(response.data?.activeRoles ?? []);
          setUserDirectory((current) => current.map((entry) => (
            (entry.userProfileId ?? entry.userSub) === (user.userProfileId ?? user.userSub)
              ? { ...entry, activeRoles }
              : entry
          )));
          setActionState({ id: userId, message: `${label} ${role} saved`, tone: "ok" });
        } catch (error) {
          setActionState({ id: userId, message: error instanceof Error ? error.message : `${label} ${role} failed`, tone: "error" });
        }
      })();
    });
  }

  function openUserMerge(source: UserDirectoryEntry) {
    const sourceKey = getUserDirectoryEntryKey(source);
    const otherUsers = userDirectory.filter((entry) => getUserDirectoryEntryKey(entry) !== sourceKey);
    const target = otherUsers[0] ?? null;
    setMergeSelection({
      source,
      targetUserKey: target ? getUserDirectoryEntryKey(target) : "",
      reason: "",
    });
  }

  function updateUserMergeTarget(targetUserKey: string) {
    setMergeSelection((current) => current ? { ...current, targetUserKey } : current);
  }

  function updateUserMergeReason(reason: string) {
    setMergeSelection((current) => current ? { ...current, reason } : current);
  }

  function runUserMergeAction() {
    if (!mergeSelection) return;
    const { source, targetUserKey, reason } = mergeSelection;
    const target = userDirectory.find((entry) => getUserDirectoryEntryKey(entry) === targetUserKey) ?? null;
    const sourceId = source.userProfileId ?? source.userSub ?? "unknown-user";
    setActionState({ id: sourceId, message: "merge pending", tone: "pending" });
    if (!target) {
      setActionState({ id: sourceId, message: "choose a target user", tone: "error" });
      return;
    }
    if (getUserDirectoryEntryKey(source) === getUserDirectoryEntryKey(target)) {
      setActionState({ id: sourceId, message: "source and target users must be different", tone: "error" });
      return;
    }
    if (dashboard.isDemo) {
      setUserDirectory((current) => mergeDemoUsers(current, source, target));
      setMergeSelection(null);
      setActionState({ id: sourceId, message: "merge saved", tone: "ok" });
      return;
    }
    if (!dashboard.canManageUsers) {
      setActionState({ id: sourceId, message: "admin role required", tone: "error" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const response = await (dataClient.mutations.mergeUserProfiles as unknown as (
            args: Record<string, unknown>,
            options: { authMode: typeof USER_POOL_AUTH_MODE },
          ) => Promise<{ errors?: Array<{ message?: string | null } | string | null> | null }>)({
            targetUserProfileId: target.userProfileId ?? undefined,
            targetUserSub: target.userSub ?? undefined,
            sourceUserProfileId: source.userProfileId ?? undefined,
            sourceUserSub: source.userSub ?? undefined,
            reason: reason.trim() || undefined,
          }, { authMode: USER_POOL_AUTH_MODE });
          assertNoGraphQLErrors(response.errors);
          await refreshEditorUserDirectory();
          setMergeSelection(null);
          setActionState({ id: sourceId, message: "merge saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: sourceId, message: error instanceof Error ? error.message : "merge failed", tone: "error" });
          await refreshEditorUserDirectory();
        }
      })();
    });
  }

  function saveCategory(category: CategorySteeringCategory, update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">) {
    setActionState({ id: category.id, message: "category save pending", tone: "pending" });
    const updatedAt = new Date().toISOString();
    if (dashboard.isDemo) {
      const nextCategory = buildCategoryCopyVersion(category, update, {
        actorLabel: "Papyrus newsroom",
        now: updatedAt,
      });
      setCategorys((current) => current.map((entry) => (entry.id === category.id ? nextCategory : entry)));
      setCategoryTreeNodes((current) => current.map((entry) => (entry.id === category.id ? nextCategory : entry)));
      setActionState({ id: category.id, message: "category copy saved", tone: "ok" });
      return;
    }
    startTransition(() => {
      void (async () => {
        try {
          const actorLabel = await getNewsDeskActorLabel();
          const nextCategory = buildCategoryCopyVersion(category, update, {
            actorLabel,
            now: updatedAt,
          });
          await dataClient.models.Category.create(nextCategory as never, { authMode: USER_POOL_AUTH_MODE });
          await dataClient.models.Category.update({
            id: category.id,
            versionState: "superseded",
            updatedAt,
          }, { authMode: USER_POOL_AUTH_MODE });
          setCategorys((current) => current.map((entry) => (entry.id === category.id ? nextCategory : entry)));
          setCategoryTreeNodes((current) => current.map((entry) => (entry.id === category.id ? nextCategory : entry)));
          setActionState({ id: category.id, message: "category copy saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: category.id, message: error instanceof Error ? error.message : "category save failed", tone: "error" });
        }
      })();
    });
  }

  function createTopicCategorySetDraft(sourceCategorySet: CategorySteeringCategorySet, displayName: string, note: string): Promise<string | null> | string | null {
    if (dashboard.isDemo) {
      const now = new Date().toISOString();
      const draftId = `category-set-demo-draft-${hashUiKey([sourceCategorySet.id, now])}`;
      const draftSet: CategorySteeringCategorySet = {
        ...sourceCategorySet,
        id: draftId,
        versionState: "draft",
        status: "draft",
        displayName: displayName.trim() || `${sourceCategorySet.displayName} Draft`,
        generatedAt: now,
      };
      const copied = categorys
        .filter((category) => category.categorySetId === sourceCategorySet.id && category.status !== "deprecated" && category.status !== "archived")
        .map((category) => ({
          ...category,
          id: `category-demo-${draftId}-${safeUiId(category.categoryKey)}`,
          categorySetId: draftId,
          versionState: "draft",
          previousVersionId: category.id,
          updatedAt: now,
      }));
      setCategorySets((current) => [draftSet, ...current]);
      setCategorys((current) => [...copied, ...current]);
      return draftId;
    }
    const createDraft = async () => {
      try {
        const response = await dataClient.mutations.createCategorySetDraft({
          sourceCategorySetId: sourceCategorySet.id,
          displayName: displayName.trim() || undefined,
          actorLabel: authState.label,
          note: note.trim() || undefined,
        }, { authMode: USER_POOL_AUTH_MODE });
        assertNoGraphQLErrors(response.errors);
        const draftId = response.data?.categorySetId ?? null;
        await refreshEditorFullDashboard();
        return draftId;
      } catch (error) {
        throw error instanceof Error ? error : new Error("draft creation failed");
      }
    };
    const draftPromise = createDraft();
    startTransition(() => {
      void draftPromise;
    });
    return draftPromise;
  }

  async function promoteTopicCategorySetDraft(categorySet: CategorySteeringCategorySet, note: string): Promise<boolean> {
    if (dashboard.isDemo) {
      setCategorySets((current) => current.map((entry) => {
        if (entry.id === categorySet.id) return { ...entry, versionState: "current", status: "accepted" };
        if (entry.lineageId && entry.lineageId === categorySet.lineageId && entry.versionState === "current") return { ...entry, versionState: "superseded", status: "superseded" };
        return entry;
      }));
      setCanonicalCategorySetId(categorySet.id);
      return true;
    }
    try {
      const response = await dataClient.mutations.promoteCategorySetDraft({
        categorySetId: categorySet.id,
        actorLabel: authState.label,
        note: note.trim() || undefined,
      }, { authMode: USER_POOL_AUTH_MODE });
      assertNoGraphQLErrors(response.errors);
      await refreshEditorFullDashboard();
      return true;
    } catch (error) {
      throw error instanceof Error ? error : new Error("draft promotion failed");
    }
  }

  async function discardTopicCategorySetDraft(categorySet: CategorySteeringCategorySet, note: string): Promise<boolean> {
    try {
      if (dashboard.isDemo) {
        setCategorySets((current) => current.filter((entry) => entry.id !== categorySet.id));
        setCategorys((current) => current.filter((entry) => entry.categorySetId !== categorySet.id));
        setCategoryKeywords((current) => current.filter((entry) => entry.categorySetId !== categorySet.id));
        setLexicalSteeringRules((current) => current.filter((entry) => entry.categorySetId !== categorySet.id));
        return true;
      }
      const response = await dataClient.mutations.discardCategorySetDraft({
        categorySetId: categorySet.id,
        actorLabel: authState.label,
        note: note.trim(),
      }, { authMode: USER_POOL_AUTH_MODE });
      assertNoGraphQLErrors(response.errors);
      await refreshEditorFullDashboard();
      return true;
    } catch (error) {
      throw error instanceof Error ? error : new Error("draft discard failed");
    }
  }

  async function createDraftTopicCategory(categorySet: CategorySteeringCategorySet, input: DraftCategoryInput): Promise<boolean> {
    try {
      if (dashboard.isDemo) {
        const now = new Date().toISOString();
        const categoryKey = safeUiId(input.displayName).replace(/-/g, "_");
        const category: CategorySteeringCategory = {
          id: `category-demo-${categorySet.id}-${categoryKey}`,
          lineageId: `category-demo-${categorySet.id}-${categoryKey}`,
          versionNumber: 1,
          versionState: "draft",
          versionCreatedAt: now,
          versionCreatedBy: authState.label,
          categorySetId: categorySet.id,
          corpusId: categorySet.corpusId,
          categoryKey,
          parentCategoryKey: input.parentCategoryKey ?? null,
          displayName: input.displayName,
          shortTitle: input.shortTitle,
          subtitle: input.subtitle,
          description: input.description,
          status: "accepted",
          updatedAt: now,
        };
        setCategorys((current) => [category, ...current]);
      } else {
        const response = await dataClient.mutations.createDraftCategory({
          categorySetId: categorySet.id,
          parentCategoryKey: input.parentCategoryKey ?? undefined,
          displayName: input.displayName,
          shortTitle: input.shortTitle ?? undefined,
          subtitle: input.subtitle ?? undefined,
          description: input.description ?? undefined,
          actorLabel: authState.label,
          note: input.note ?? undefined,
        }, { authMode: USER_POOL_AUTH_MODE });
        assertNoGraphQLErrors(response.errors);
        await refreshEditorFullDashboard();
      }
      return true;
    } catch (error) {
      throw error instanceof Error ? error : new Error("topic creation failed");
    }
  }

  async function updateDraftTopicCategory(category: CategorySteeringCategory, input: DraftCategoryInput): Promise<boolean> {
    try {
      if (dashboard.isDemo) {
        setCategorys((current) => current.map((entry) => entry.id === category.id ? { ...entry, ...input, updatedAt: new Date().toISOString() } : entry));
      } else {
        const response = await dataClient.mutations.updateDraftCategory({
          categoryId: category.id,
          parentCategoryKey: input.parentCategoryKey ?? undefined,
          displayName: input.displayName,
          shortTitle: input.shortTitle ?? undefined,
          subtitle: input.subtitle ?? undefined,
          description: input.description ?? undefined,
          actorLabel: authState.label,
          note: input.note ?? undefined,
        }, { authMode: USER_POOL_AUTH_MODE });
        assertNoGraphQLErrors(response.errors);
        await refreshEditorFullDashboard();
      }
      return true;
    } catch (error) {
      throw error instanceof Error ? error : new Error("topic update failed");
    }
  }

  async function archiveDraftTopicCategory(category: CategorySteeringCategory, note: string): Promise<boolean> {
    try {
      if (dashboard.isDemo) {
        setCategorys((current) => current.map((entry) => entry.id === category.id ? { ...entry, status: "deprecated", updatedAt: new Date().toISOString() } : entry));
      } else {
        const response = await dataClient.mutations.archiveDraftCategory({
          categoryId: category.id,
          actorLabel: authState.label,
          note: note.trim() || undefined,
        }, { authMode: USER_POOL_AUTH_MODE });
        assertNoGraphQLErrors(response.errors);
        await refreshEditorFullDashboard();
      }
      return true;
    } catch (error) {
      throw error instanceof Error ? error : new Error("topic archive failed");
    }
  }

  function runReferenceTopicLabelAction(input: {
    action: TopicLabelAction;
    category: CategorySteeringCategory;
    note?: string | null;
    reference: ReferenceRecord;
    sourceRelationId?: string | null;
  }) {
    const actionId = input.sourceRelationId ?? `${input.reference.id}:${input.category.id}:${input.action}`;
    setActionState({ id: actionId, message: "topic label action pending", tone: "pending" });
    startTransition(() => {
      void (async () => {
        try {
          if (dashboard.isDemo) {
            const now = new Date().toISOString();
            if (input.action === "reject_prediction" || input.action === "unlabel") {
              setSemanticRelations((current) => current.filter((relation) => relation.id !== input.sourceRelationId));
            } else {
              const relation = buildUiAuthoritativeLabelRelation(input.reference, input.category, authState.label, input.note ?? null, now, input.sourceRelationId ?? null);
              setSemanticRelations((current) => [relation, ...current.filter((entry) => entry.id !== relation.id)]);
            }
          } else {
            const response = await dataClient.mutations.reviewReferenceTopicLabel({
              referenceId: input.reference.id,
              categoryId: input.category.id,
              action: input.action,
              sourceRelationId: input.sourceRelationId ?? undefined,
              actorLabel: authState.label,
              note: input.note?.trim() || undefined,
            }, { authMode: USER_POOL_AUTH_MODE });
            assertNoGraphQLErrors(response.errors);
            await refreshEditorFullDashboard();
          }
          setActionState({ id: actionId, message: "topic label action saved", tone: "ok" });
        } catch (error) {
          setActionState({ id: actionId, message: error instanceof Error ? error.message : "topic label action failed", tone: "error" });
        }
      })();
    });
  }

  return (
    <main
      className="site-shell news-desk-shell"
      data-news-desk
      data-category-steering
      data-category-steering-demo={dashboard.isDemo ? "true" : "false"}
      data-news-desk-refreshing={isRefreshing ? "true" : "false"}
      data-news-desk-drawer-docked={drawerController.isDocked ? "true" : "false"}
      data-news-desk-drawer-open={drawerController.open ? "true" : "false"}
      data-rhythm-overlay={showRhythmOverlay ? "true" : "false"}
    >
      <NewsroomProgressBackLink
        searchAction={canEdit && editorShellReady && !dashboard.isDemo ? {
          disabled: false,
          onPress: activeTab === "search"
            ? focusNewsroomSearchForm
            : topBarSearchControl.open,
        } : null}
      />
      <section className="scroll-edition news-desk-edition">
        <div className="paper-page paper-page--front paper-page--active">
          <article className="paper-page-content paper-page-content--front news-desk-page" aria-labelledby="news-desk-title">
	        <header className="masthead news-desk-masthead">
	          <div className="masthead__rule" />
	          <h1 id="news-desk-title">
	            {isSectionPage ? mastheadTitle : <Link href={getNewsDeskTabHref("/newsroom", dashboard.isDemo)}>NEWSROOM</Link>}
	          </h1>
		          <div className="masthead__meta" aria-label="Newsroom edition status">
	            <span><NewsDeskDrawerTrigger controller={drawerController} /></span>
	            <span aria-hidden="true" className="masthead__meta-placeholder">&nbsp;</span>
	            <span>{dashboard.isDemo ? "Demo Desk" : <Link className="news-desk-auth-control-link" href="/settings">Settings</Link>}</span>
	          </div>
	        </header>
        <NewsDeskDrawerPanel activeTab={activeTab} controller={drawerController} demo={dashboard.isDemo} />

        {!isSectionPage && activeTab === "overview" ? (
          <nav className="news-desk-tabs" aria-label="Newsroom sections">
            {NEWS_DESK_TABS.map((tab) => (
              <NewsDeskTabLink
                key={tab.id}
                active={tab.id === activeTab}
                count={tabCounts[tab.id]}
                countSlot={tab.id !== "administration"}
                countVisible={tab.id === "administration" || summaryStatus !== "loading"}
                countMissing={tab.id !== "administration" && summaryStatus === "missing"}
                demo={dashboard.isDemo}
                tab={tab}
              />
            ))}
          </nav>
        ) : null}

        {activeTab !== "overview" && activeTab !== "assignments" && activeTab !== "messages" && activeTab !== "references" && activeTab !== "topics" && activeTab !== "concepts" && activeTab !== "search" ? (
          <section className="news-desk-lede-grid" aria-label="Newsroom overview">
            <article className="news-desk-lede">
              <h2>{formatDeskSectionHeadline(activeTab)}</h2>
              <p>{formatDeskSectionLede(activeTab)}</p>
            </article>
          </section>
        ) : null}

        {isRefreshing ? (
          <div className="category-steering-alert" role="status">
            Refreshing newsroom data...
          </div>
        ) : null}
        {!isRefreshing && shellError ? (
          <div className="category-steering-alert" role="status">
            {shellError}
          </div>
        ) : null}
        {actionState ? (
          <div className={`category-steering-action category-steering-action--${actionState.tone}`} role="status" aria-live="polite">
            {actionState.message}
          </div>
        ) : null}

        {isSectionPage ? (
          <DeepNewsroomSectionView
            demo={Boolean(dashboard.isDemo)}
            disabled={controlsDisabled}
            onCreateInsight={createInsight}
            section={activeNewsroomSection}
            sectionId={sectionPageId ?? ""}
            sectionsLoaded={loadedSections.sections}
          />
        ) : null}
        {!isSectionPage && activeTab === "overview" ? (
          <OverviewDeskView
            assignments={assignments}
            dashboard={dashboard}
            initialForumThreadId={initialSelection.forumThread}
            isDemo={Boolean(dashboard.isDemo)}
            newsroomSections={newsroomSections}
          />
        ) : null}
        {!isSectionPage && activeTab === "search" ? (
          <SearchDeskView
            assignments={assignments}
            categories={mergeCategoryRecords(categorys, activeCategoryTreeNodes)}
            initialRequest={initialSearchRequest}
            isDemo={Boolean(dashboard.isDemo)}
            messages={messages}
            references={references}
            semanticNodes={semanticNodes}
          />
        ) : null}
        {!isSectionPage && activeTab === "desks" ? (
          <DesksDeskView
            assignments={assignments}
            categoryByUid={categoryByUid}
            categoryNodes={activeCategoryTreeNodes}
            disabled={controlsDisabled}
            doctrineRecords={doctrineRecords}
            graph={graph}
            initialCategoryLineageId={initialSelection.category}
            isDemo={Boolean(dashboard.isDemo)}
            onCategorySave={saveCategory}
            onDeskDoctrineSave={saveCategoryDoctrine}
            rootCategories={rootDeskCategories}
            statusMessage={actionState}
          />
        ) : null}
        {!isSectionPage && activeTab === "topics" ? (
          <TopicsDeskView
            activeCategoryTree={activeCategoryTree}
            activeCategorySet={activeCategorySet}
            analysisProfiles={analysisProfiles}
            canonicalCategorys={canonicalCategorys}
            categorySets={categorySets}
            categorys={categorys}
            categoryByUid={categoryByUid}
            categoryKeywords={categoryKeywords}
            categoryTreeLoadError={categoryTreeLoadError}
            categoryNodes={activeCategoryTreeNodes}
            corpora={mergeAnalysisCorpora(configuredCorpora, corpora)}
            disabled={controlsDisabled}
            graph={graph}
            initialCategoryLineageId={initialSelection.category}
            isDemo={Boolean(dashboard.isDemo)}
            lexicalSteeringRules={lexicalSteeringRules}
            references={references}
            semanticRelations={semanticRelations}
            onArchiveDraftCategory={archiveDraftTopicCategory}
            onCategorySave={saveCategory}
            onCreateAnalysisReindexAssignment={createAnalysisReindexAssignment}
            onCreateDraftCategory={createDraftTopicCategory}
            onCreateDraftSet={createTopicCategorySetDraft}
            onDiscardDraftSet={discardTopicCategorySetDraft}
            onLexicalRuleCreate={createLexicalSteeringRule}
            onPromoteDraftSet={promoteTopicCategorySetDraft}
            onProposalAction={runProposalAction}
            onReviewTopicLabel={runReferenceTopicLabelAction}
            onUpdateDraftCategory={updateDraftTopicCategory}
            proposals={proposals}
          />
        ) : null}
        {!isSectionPage && activeTab === "concepts" ? (
          <ConceptsDeskView
            categories={mergeCategoryRecords(categorys, activeCategoryTreeNodes)}
            disabled={controlsDisabled}
            graph={graph}
            initialCategoryLineageId={initialSelection.category}
            initialNodeLineageId={initialSelection.node}
            onCreateInsight={createInsight}
            semanticNodes={semanticNodes}
            summary={summary}
          />
        ) : null}
        {!isSectionPage && activeTab === "references" ? (
          <ReferencesDeskView
            categories={mergeCategoryRecords(categorys, activeCategoryTreeNodes)}
            categorySets={categorySets}
            corpora={corpora}
            curationRunsByLineage={referenceCurationRunsByLineage}
            graph={graph}
            initialCategoryLineageId={initialSelection.category}
            initialReferenceLineageId={initialSelection.reference}
            isDemo={Boolean(dashboard.isDemo)}
            deepLinkFetchEnabled={
              authState.status === "signedIn"
              && (
                Boolean(initialSelection.reference)
                || Boolean(pathnameReferenceLineageId)
                || hasHydratedReferences
              )
            }
            qualityActionState={referenceQualityActionState}
            references={references}
            referenceAttachments={referenceAttachments}
            realtimeError={referencesRealtimeError}
            realtimeStatus={referencesRealtimeStatus}
            semanticRelations={semanticRelations}
            summary={summary}
            disabled={controlsDisabled}
            onMoveCorpus={runReferenceCorpusMove}
            onReview={runReferenceCurationAction}
            onStartCuration={runReferenceCurationStart}
            onSetQualityRating={runReferenceQualityRating}
            onCreateInsight={createInsight}
            onReviewTopicLabel={runReferenceTopicLabelAction}
            onHydrateReference={hydrateReferenceFromRoute}
          />
        ) : null}
        {!isSectionPage && activeTab === "insights" ? (
          <InsightsDeskView
            graph={graph}
            initialThreadId={initialSelection.forumThread}
            isDemo={Boolean(dashboard.isDemo)}
            messages={messages}
            summary={summary}
          />
        ) : null}
        {!isSectionPage && activeTab === "messages" ? (
          <MessagesDeskView
            assignments={assignments}
            graph={graph}
            initialForumThreadId={initialSelection.forumThread}
            initialMessageId={initialSelection.message}
            isDemo={Boolean(dashboard.isDemo)}
            messages={messages}
            newsroomSections={newsroomSections}
            summary={summary}
          />
        ) : null}
        {!isSectionPage && activeTab === "assignments" ? (
          <AssignmentDeskView
            actionState={actionState}
            analysisProfiles={analysisProfiles}
            assignmentEvents={assignmentEvents}
            assignments={assignments}
            editionSlots={editionSlots}
            corpora={mergeAnalysisCorpora(configuredCorpora, corpora)}
            messages={messages}
            graph={graph}
            semanticRelations={semanticRelations}
            initialAssignmentId={initialSelection.assignment}
            initialView={initialSelection.assignmentView}
            isDemo={Boolean(dashboard.isDemo)}
            newsroomSections={newsroomSections}
            summary={summary}
            disabled={controlsDisabled}
            onAction={runAssignmentAction}
            onCreateAnalysisReindexAssignment={createAnalysisReindexAssignment}
            onReviewReportingPacket={runReportingPacketReview}
          />
        ) : null}
        {!isSectionPage && activeTab === "administration" ? (
          <AdministrationDeskView
            actionState={actionState}
            administrationPanel={administrationPanel}
            canManageUsers={Boolean(dashboard.canManageUsers)}
            disabled={controlsDisabled}
            doctrineDrafts={doctrineDrafts}
            doctrineRecords={doctrineRecords}
            isDemo={Boolean(dashboard.isDemo)}
            mergeSelection={mergeSelection}
            newsroomSections={newsroomSections}
            doctrineCategories={acceptedDoctrineCategories}
            onCancelMerge={() => setMergeSelection(null)}
            onConfirmMerge={runUserMergeAction}
            onMergeReasonChange={updateUserMergeReason}
            onMergeRequest={openUserMerge}
            onMergeTargetChange={updateUserMergeTarget}
            onPanelChange={setAdministrationPanel}
            onPolicyChange={updateDoctrineDraft}
            onPolicySave={saveDoctrine}
            onCategoryDoctrineSave={saveCategoryDoctrine}
            onSectionReorder={runSectionReorder}
            onSectionSave={runSectionUpsert}
            onRoleAction={runUserRoleAction}
            onProcedureDefinitionSave={runProcedureDefinitionSave}
            onProcedureVersionDraftSave={runProcedureVersionDraftSave}
            onProcedureVersionPublish={runProcedureVersionPublish}
            onProcedureRun={runProcedureNow}
            procedures={procedureDefinitions}
            procedureVersions={procedureVersions}
            procedureRuns={procedureRuns}
            users={userDirectory}
          />
        ) : null}
        {topBarSearchControl.dialog}
          </article>
        </div>
      </section>
    </main>
  );
}

function OverviewDeskView({
  assignments,
  dashboard,
  initialForumThreadId = null,
  isDemo: isDemoProp = false,
  newsroomSections,
}: {
  assignments: AssignmentRecord[];
  dashboard: CategorySteeringDashboard;
  initialForumThreadId?: string | null;
  isDemo?: boolean;
  newsroomSections: NewsroomSectionRecord[];
}) {
  const isDemo = Boolean(dashboard.isDemo || isDemoProp);
  const forumMessageAnchorId = useForumMessageAnchorId();
  const [overviewEditionInputs, setOverviewEditionInputs] = useState<{
    editions: EditionRecord[];
    editionSlots: EditionSlotRecord[];
    assignments: AssignmentRecord[];
    loaded: boolean;
    error: string | null;
  }>({
    editions: [],
    editionSlots: dashboard.editionSlots,
    assignments,
    loaded: false,
    error: null,
  });
  const availableSections = useMemo(
    () => sortNewsroomSections(newsroomSections).filter(isEnabledNewsroomSection),
    [newsroomSections],
  );

  useEffect(() => {
    let active = true;
    if (isDemo) {
      setOverviewEditionInputs({
        editions: [],
        editionSlots: dashboard.editionSlots,
        assignments,
        loaded: true,
        error: null,
      });
      return () => {
        active = false;
      };
    }
    setOverviewEditionInputs((current) => ({ ...current, loaded: false, error: null }));
    void loadEditorOverviewEditionData()
      .then((data) => {
        if (!active) return;
        setOverviewEditionInputs({
          editions: data.editions,
          editionSlots: data.editionSlots,
          assignments: data.assignments,
          loaded: true,
          error: null,
        });
      })
      .catch((error) => {
        if (!active) return;
        setOverviewEditionInputs({
          editions: [],
          editionSlots: dashboard.editionSlots,
          assignments,
          loaded: true,
          error: error instanceof Error ? error.message : "Could not load overview edition data.",
        });
      });
    return () => {
      active = false;
    };
  }, [assignments, dashboard.editionSlots, isDemo]);

  const overviewEditions = useMemo(
    () => resolveOverviewEditions({
      editions: overviewEditionInputs.editions,
      editionSlots: overviewEditionInputs.editionSlots,
      assignments: overviewEditionInputs.assignments,
    }),
    [overviewEditionInputs.assignments, overviewEditionInputs.editionSlots, overviewEditionInputs.editions],
  );
  const [selectedEditionId, setSelectedEditionId] = useState("");
  const [selectedSectionId, setSelectedSectionId] = useState("");
  const [statusFilter, setStatusFilter] = useState<"active" | "all">("active");
  const [threads, setThreads] = useState<ForumThreadWithMessages[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [threadsError, setThreadsError] = useState<string | null>(null);
  const [selectedThreadId, setSelectedThreadId] = useState("");
  const [forumView, setForumView] = useState<ForumViewState>({ mode: "index" });
  const [replyParentId, setReplyParentId] = useState("");
  const [composeSummary, setComposeSummary] = useState("");
  const [composeContent, setComposeContent] = useState("");
  const [composeError, setComposeError] = useState<string | null>(null);
  const [newThreadDraft, setNewThreadDraft] = useState<ForumNewThreadDraft>(createDefaultForumNewThreadDraft(""));
  const [newThreadOpen, setNewThreadOpen] = useState(false);
  const [newThreadError, setNewThreadError] = useState<string | null>(null);
  const [deletingMessageId, setDeletingMessageId] = useState("");
  const [viewFilter, setViewFilter] = useState<"all" | "edition" | "section">("all");

  useEffect(() => {
    if (!availableSections.length) {
      setSelectedSectionId("");
      setNewThreadDraft((current) => ({ ...current, sectionId: "" }));
      return;
    }
    if (!selectedSectionId || !availableSections.some((section) => section.id === selectedSectionId)) {
      setSelectedSectionId(availableSections[0].id);
    }
    setNewThreadDraft((current) => (
      current.sectionId
        ? current
        : { ...current, sectionId: availableSections[0].id }
    ));
  }, [availableSections, selectedSectionId]);

  useEffect(() => {
    if (!overviewEditions.length) {
      setSelectedEditionId("");
      return;
    }
    if (selectedEditionId && overviewEditions.some((edition) => edition.editionId === selectedEditionId)) {
      return;
    }
    const preferred = overviewEditions.find((edition) => edition.isNearestUpcoming) ?? overviewEditions[0];
    setSelectedEditionId(preferred.editionId);
  }, [overviewEditions, selectedEditionId]);

  const refreshThreads = useCallback(async () => {
    if (!selectedEditionId) {
      setThreads([]);
      setThreadsError(null);
      return;
    }
    setThreadsLoading(true);
    try {
      const section = availableSections.find((entry) => entry.id === selectedSectionId) ?? null;
      const result = await loadEditionForumThreads({
        editionId: selectedEditionId,
        sectionId: selectedSectionId || undefined,
        sectionKey: section?.id ?? undefined,
        includeMessages: true,
        status: statusFilter === "active" ? "active" : "",
      });
      const merged = [...result.editionThreads, ...result.sectionThreads].sort(
        (left, right) => String(right.lastMessageAt ?? right.updatedAt ?? "").localeCompare(String(left.lastMessageAt ?? left.updatedAt ?? "")),
      );
      setThreads(merged);
      setThreadsError(null);
      setSelectedThreadId((current) => (current && merged.some((thread) => thread.id === current) ? current : ""));
    } catch (error) {
      setThreads([]);
      setThreadsError(error instanceof Error ? error.message : "Could not load edition forum threads.");
    } finally {
      setThreadsLoading(false);
    }
  }, [availableSections, selectedEditionId, selectedSectionId, statusFilter]);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  const selectedEdition = overviewEditions.find((edition) => edition.editionId === selectedEditionId) ?? null;
  const filteredThreads = useMemo(() => {
    if (viewFilter === "edition") return threads.filter((thread) => thread.scope === "edition");
    if (viewFilter === "section") return threads.filter((thread) => thread.scope === "section");
    return threads;
  }, [threads, viewFilter]);
  const selectedThread = filteredThreads.find((thread) => thread.id === selectedThreadId) ?? null;

  const openThread = useCallback((threadId: string, options?: { messageId?: string | null; replace?: boolean }) => {
    setSelectedThreadId(threadId);
    setForumView({ mode: "thread", threadId });
    pushForumThreadUrl(threadId, {
      demo: isDemo,
      messageId: options?.messageId,
      replace: options?.replace,
    });
  }, [isDemo]);

  const closeThread = useCallback(() => {
    setSelectedThreadId("");
    setForumView({ mode: "index" });
    pushForumThreadUrl(null, { demo: isDemo, replace: true });
  }, [isDemo]);

  useEffect(() => {
    const threadId = initialForumThreadId ?? readCurrentForumRoute().threadId;
    if (!threadId || threadsLoading) return;
    if (!threads.some((thread) => thread.id === threadId)) return;
    if (selectedThreadId === threadId && forumView.mode === "thread") return;
    setSelectedThreadId(threadId);
    setForumView({ mode: "thread", threadId });
  }, [forumView.mode, initialForumThreadId, selectedThreadId, threads, threadsLoading]);

  useEffect(() => {
    const handlePopState = () => {
      const route = readCurrentForumRoute();
      if (route.threadId) {
        setSelectedThreadId(route.threadId);
        setForumView({ mode: "thread", threadId: route.threadId });
        return;
      }
      setSelectedThreadId("");
      setForumView({ mode: "index" });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const submitNewThread = useCallback(async () => {
    if (!selectedEditionId) return;
    const title = newThreadDraft.title.trim();
    const content = newThreadDraft.content.trim();
    if (!title) {
      setNewThreadError("Thread title is required.");
      return;
    }
    if (!content) {
      setNewThreadError("Thread body is required.");
      return;
    }
    try {
      let threadId = "";
      if (newThreadDraft.scope === "section") {
        const sectionId = String(newThreadDraft.sectionId || selectedSectionId || "").trim();
        const section = availableSections.find((entry) => entry.id === sectionId) ?? null;
        if (!section) {
          setNewThreadError("Section is required for section threads.");
          return;
        }
        const created = await createSectionForumThreadRecord({
          editionId: selectedEditionId,
          sectionId: section.id,
          sectionKey: section.id,
          sectionTitle: section.title,
          title,
          actorLabel: "human-editor",
        });
        threadId = created.thread.id;
      } else {
        const ensured = await ensureEditionForumThreadRecord({
          editionId: selectedEditionId,
          actorLabel: "human-editor",
        });
        threadId = ensured.thread.id;
      }
      await appendForumThreadMessageRecord({
        threadId,
        summary: title,
        content,
        role: "human",
        authorLabel: "human-editor",
      });
      await refreshThreads();
      openThread(threadId, { replace: true });
      setNewThreadDraft(createDefaultForumNewThreadDraft(selectedSectionId || availableSections[0]?.id || ""));
      setNewThreadOpen(false);
      setNewThreadError(null);
    } catch (error) {
      setNewThreadError(error instanceof Error ? error.message : "Could not create thread.");
    }
  }, [availableSections, newThreadDraft, openThread, refreshThreads, selectedEditionId, selectedSectionId]);

  const postThreadMessage = useCallback(async () => {
    if (!selectedThread) return;
    const content = composeContent.trim();
    if (!content) {
      setComposeError("Message content is required.");
      return;
    }
    const summary = composeSummary.trim() || content.slice(0, 120);
    setComposeError(null);
    try {
      await appendForumThreadMessageRecord({
        threadId: selectedThread.id,
        summary,
        content,
        role: "human",
        authorLabel: "human-editor",
        parentMessageId: replyParentId || undefined,
      });
      setComposeSummary("");
      setComposeContent("");
      setReplyParentId("");
      await refreshThreads();
      setForumView({ mode: "thread", threadId: selectedThread.id });
    } catch (error) {
      setComposeError(error instanceof Error ? error.message : "Could not post thread message.");
    }
  }, [composeContent, composeSummary, refreshThreads, replyParentId, selectedThread]);

  const deleteThreadMessage = useCallback(async (threadId: string, messageId: string) => {
    setDeletingMessageId(messageId);
    try {
      await deleteForumThreadMessageRecord({ threadId, messageId });
      if (replyParentId === messageId) setReplyParentId("");
      await refreshThreads();
      setComposeError(null);
    } catch (error) {
      setComposeError(error instanceof Error ? error.message : "Could not delete message.");
    } finally {
      setDeletingMessageId("");
    }
  }, [refreshThreads, replyParentId]);
  return (
    <div className="news-desk-overview" data-news-desk-section="overview">
      <div className="news-desk-overview-feeds news-desk-overview-forum" data-newsroom-overview-feeds>
        <NewsroomListDetailShell
          sectionKey="messages"
          canExpandDetail={forumView.mode === "thread" && Boolean(forumView.threadId)}
          detailOpen={forumView.mode === "thread" && Boolean(forumView.threadId)}
          selectionScrollKey={forumView.mode === "thread" ? forumView.threadId : null}
          lede={(
            <NewsroomDeskSectionLede
              headingId="overview-edition-forum-title"
              section="messages"
              headline="Forum"
              lede="Edition and section threads for coordinating the upcoming issue."
              controls={null}
            />
          )}
          list={(
            <section className="category-steering-section category-steering-section--lead" aria-label="Edition forum threads">
              <ForumThreadIndex
                threads={filteredThreads}
                sections={availableSections}
                isLoading={threadsLoading}
                error={threadsError}
                emptyLabel={overviewEditions.length ? "No forum threads for this edition/filter." : "No edition candidates found in assignments or slots."}
                toolbar={(
                  <div className="news-desk-forum-toolbar">
                    <select
                      aria-label="Forum edition"
                      value={selectedEditionId}
                      onChange={(event) => setSelectedEditionId(event.target.value)}
                    >
                      {overviewEditions.length ? overviewEditions.map((edition) => (
                        <option key={edition.editionId} value={edition.editionId}>
                          {edition.label}
                        </option>
                      )) : <option value="">No upcoming edition candidates</option>}
                    </select>
                    <select
                      aria-label="Forum scope"
                      value={viewFilter}
                      onChange={(event) => setViewFilter(event.target.value === "edition" ? "edition" : event.target.value === "section" ? "section" : "all")}
                    >
                      <option value="all">All scopes</option>
                      <option value="edition">Edition</option>
                      <option value="section">Section</option>
                    </select>
                    <select
                      aria-label="Forum section"
                      value={selectedSectionId}
                      onChange={(event) => {
                        setSelectedSectionId(event.target.value);
                        setNewThreadDraft((current) => ({ ...current, sectionId: event.target.value }));
                      }}
                    >
                      <option value="">All sections</option>
                      {availableSections.map((section) => (
                        <option key={section.id} value={section.id}>{section.title}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Forum status"
                      value={statusFilter}
                      onChange={(event) => setStatusFilter(event.target.value === "all" ? "all" : "active")}
                    >
                      <option value="active">Active</option>
                      <option value="all">All</option>
                    </select>
                    <button
                      type="button"
                      disabled={!selectedEditionId}
                      onClick={() => {
                        setNewThreadOpen((value) => !value);
                        setForumView({ mode: "index" });
                      }}
                    >
                      {newThreadOpen ? "Close New Thread" : "New Thread"}
                    </button>
                  </div>
                )}
                composer={newThreadOpen ? (
                  <ForumThreadComposer
                    draft={newThreadDraft}
                    sections={availableSections}
                    error={newThreadError}
                    onChange={setNewThreadDraft}
                    onCancel={() => {
                      setNewThreadOpen(false);
                      setNewThreadError(null);
                    }}
                    onSubmit={() => void submitNewThread()}
                  />
                ) : null}
                onOpenThread={(threadId) => openThread(threadId)}
              />
            </section>
          )}
          detail={forumView.mode === "thread" && selectedThread ? (
            <ForumThreadView
              thread={selectedThread}
              sections={availableSections}
              replyParentId={replyParentId}
              composeSummary={composeSummary}
              composeContent={composeContent}
              composeError={composeError}
              focusMessageId={forumMessageAnchorId}
              isDemo={isDemo}
              onBack={closeThread}
              onReplyTarget={(messageId) => {
                setReplyParentId(messageId);
                pushForumThreadUrl(selectedThread.id, { demo: isDemo, messageId, replace: true });
              }}
              onClearReplyTarget={() => {
                setReplyParentId("");
                pushForumThreadUrl(selectedThread.id, { demo: isDemo, replace: true });
              }}
              onSummaryChange={setComposeSummary}
              onContentChange={setComposeContent}
              onSubmit={() => void postThreadMessage()}
              onDeleteMessage={(messageId) => {
                if (!selectedThread || deletingMessageId === messageId) return;
                void deleteThreadMessage(selectedThread.id, messageId);
              }}
              deletingMessageId={deletingMessageId}
            />
          ) : forumView.mode === "thread" ? (
            <section className="category-steering-section">
              <SectionHeader title="Thread Unavailable" detail="Forum" />
              <EmptyRow label="That thread is not available under the current filters. Return to Threads and adjust filters." />
              <button type="button" onClick={closeThread}>Back to Threads</button>
            </section>
          ) : (
            <section className="category-steering-section">
              <SectionHeader title="Forum Threads" detail="Thread index" />
              <EmptyRow label="Select a topic from the index to open the thread." />
            </section>
          )}
        />
        {!selectedEdition && overviewEditions.length ? (
          <div className="category-steering-alert" data-tone="warning">
            Selecting default edition...
          </div>
        ) : null}
        {overviewEditionInputs.loaded && !overviewEditionInputs.editions.length ? (
          <div className="category-steering-alert">
            No upcoming edition found yet. Create or update a dated Edition first.
          </div>
        ) : null}
        {overviewEditionInputs.loaded && overviewEditionInputs.editions.length > 0 && !threadsLoading && !threads.length ? (
          <div className="category-steering-alert">
            Edition found, but no forum threads are active yet. Use New Thread to start one.
          </div>
        ) : null}
        {overviewEditionInputs.error ? (
          <div className="category-steering-alert" data-tone="error">
            {overviewEditionInputs.error}
          </div>
        ) : null}
      </div>
      <NewsroomSectionRail demo={isDemo} sections={newsroomSections} />
    </div>
  );
}

type EditionResolutionSource = "edition_record" | "edition_slot" | "assignment" | "thread_activity";

type ResolvedOverviewEdition = {
  editionId: string;
  editionDate: string | null;
  isNearestUpcoming: boolean;
  label: string;
  resolutionSource: EditionResolutionSource;
};

function resolveOverviewEditions({
  editions,
  editionSlots,
  assignments,
}: {
  editions: EditionRecord[];
  editionSlots: EditionSlotRecord[];
  assignments: AssignmentRecord[];
}): ResolvedOverviewEdition[] {
  const candidates = new Map<string, { editionDate: string | null; sources: Set<EditionResolutionSource> }>();
  const upsertCandidate = (editionId: string | null, editionDate: string | null, source: EditionResolutionSource) => {
    const cleanId = String(editionId ?? "").trim();
    if (!cleanId) return;
    const current = candidates.get(cleanId);
    const normalizedDate = normalizeIsoDateOnly(editionDate) ?? extractIsoDateFromEditionId(cleanId);
    if (!current) {
      candidates.set(cleanId, { editionDate: normalizedDate, sources: new Set([source]) });
      return;
    }
    if (!current.editionDate && normalizedDate) current.editionDate = normalizedDate;
    current.sources.add(source);
  };

  for (const edition of editions) {
    upsertCandidate(
      normalizeMetadataString(edition.id),
      normalizeMetadataString(edition.editionDate),
      "edition_record",
    );
  }

  for (const slot of editionSlots) {
    const slotMetadata = metadataRecord(slot.metadata);
    upsertCandidate(
      normalizeMetadataString(slot.editionId),
      normalizeMetadataString(slotMetadata?.editionDate),
      "edition_slot",
    );
  }

  for (const assignment of assignments) {
    const metadata = metadataRecord(assignment.metadata);
    const editionId = normalizeEditionIdFromAssignment(assignment, metadata);
    const slotTarget = metadataRecord(metadata?.slotTarget);
    upsertCandidate(
      editionId,
      normalizeMetadataString(metadata?.editionDate) ?? normalizeMetadataString(slotTarget?.editionDate),
      "assignment",
    );
  }

  const now = new Date();
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const rows = Array.from(candidates.entries()).map(([editionId, value]) => ({
    editionId,
    editionDate: value.editionDate,
    source: resolveEditionResolutionSource(value.sources),
    dayDelta: dayDeltaFromToday(value.editionDate, today),
  }));
  const upcomingRows = rows
    .filter((row) => row.dayDelta !== null && row.dayDelta >= 0)
    .sort((left, right) => (
      Number(left.dayDelta ?? Number.MAX_SAFE_INTEGER) - Number(right.dayDelta ?? Number.MAX_SAFE_INTEGER)
      || String(left.editionDate ?? "").localeCompare(String(right.editionDate ?? ""))
      || left.editionId.localeCompare(right.editionId)
    ));
  const nearestUpcomingId = upcomingRows[0]?.editionId ?? null;
  const sortedRows = rows.sort((left, right) => {
    if (nearestUpcomingId) {
      if (left.editionId === nearestUpcomingId) return -1;
      if (right.editionId === nearestUpcomingId) return 1;
    }
    const leftUpcoming = left.dayDelta !== null && left.dayDelta >= 0;
    const rightUpcoming = right.dayDelta !== null && right.dayDelta >= 0;
    if (leftUpcoming !== rightUpcoming) return leftUpcoming ? -1 : 1;
    if (leftUpcoming && rightUpcoming) {
      return Number(left.dayDelta ?? Number.MAX_SAFE_INTEGER) - Number(right.dayDelta ?? Number.MAX_SAFE_INTEGER)
        || String(left.editionDate ?? "").localeCompare(String(right.editionDate ?? ""))
        || left.editionId.localeCompare(right.editionId);
    }
    return String(right.editionDate ?? "").localeCompare(String(left.editionDate ?? ""))
      || left.editionId.localeCompare(right.editionId);
  });
  return sortedRows.map((row) => ({
    editionId: row.editionId,
    editionDate: row.editionDate,
    isNearestUpcoming: row.editionId === nearestUpcomingId,
    label: row.editionDate ? `${row.editionDate} · ${row.editionId}` : row.editionId,
    resolutionSource: row.source,
  }));
}

function resolveEditionResolutionSource(sources: Set<EditionResolutionSource>): EditionResolutionSource {
  if (sources.has("edition_record")) return "edition_record";
  if (sources.has("edition_slot")) return "edition_slot";
  if (sources.has("assignment")) return "assignment";
  return "thread_activity";
}

function normalizeIsoDateOnly(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = String(value).trim().match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
}

function extractIsoDateFromEditionId(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = String(value).match(/(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
}

function dayDeltaFromToday(dateText: string | null, today: Date): number | null {
  if (!dateText) return null;
  const parsed = new Date(`${dateText}T00:00:00.000Z`);
  if (Number.isNaN(parsed.valueOf())) return null;
  return Math.round((parsed.valueOf() - today.valueOf()) / 86400000);
}

function NewsroomSectionRail({
  demo,
  sections,
}: {
  demo: boolean;
  sections: NewsroomSectionRecord[];
}) {
  const enabledSections = useMemo(() => sortNewsroomSections(sections).filter(isEnabledNewsroomSection), [sections]);
  const canonicalSections = enabledSections.filter((section) => normalizeNewsroomSectionType(section.type) === "canonical");
  const rotatingSections = enabledSections.filter((section) => normalizeNewsroomSectionType(section.type) === "floating");
  const hasVisibleSectionContent = canonicalSections.length > 0 || rotatingSections.length > 0;
  const railRef = useRef<HTMLElement | null>(null);
  const hasAnimatedRailRef = useRef(false);

  useLayoutEffect(() => {
    const rail = railRef.current;
    if (!rail) return;

    gsap.killTweensOf(rail);

    if (!hasVisibleSectionContent) {
      hasAnimatedRailRef.current = false;
      rail.style.opacity = "";
      rail.style.visibility = "";
      return;
    }

    if (!hasAnimatedRailRef.current) {
      hasAnimatedRailRef.current = true;
      gsap.fromTo(
        rail,
        { autoAlpha: 0 },
        { autoAlpha: 1, duration: 1.35, ease: "sine.out" },
      );
      return;
    }

    gsap.set(rail, { autoAlpha: 1 });
  }, [hasVisibleSectionContent]);


  if (!hasVisibleSectionContent) return null;

  return (
    <aside className="newsroom-section-rail" data-newsroom-section-rail aria-labelledby="newsroom-section-rail-title" ref={railRef}>
      <header className="newsroom-section-rail__header">
        <p className="story-label">Sections</p>
        <h2 id="newsroom-section-rail-title">Section Desk</h2>
      </header>
      <div className="newsroom-section-rail__body">
        {canonicalSections.length ? (
          <div className="newsroom-section-rail__canonical-list" data-newsroom-section-rail-canonical-list>
            {canonicalSections.map((section) => (
              <Link
                className="newsroom-section-rail__link"
                data-newsroom-section-link={section.id}
                data-newsroom-section-type="canonical"
                href={buildNewsroomSectionHref(section.id, demo)}
                key={section.id}
              >
                <span className="newsroom-section-rail__link-text">
                  <span>{section.title}</span>
                  <small>{displayNewsroomSectionShortTitle(section)}</small>
                </span>
              </Link>
            ))}
          </div>
        ) : null}
        {rotatingSections.length ? (
          <NewsroomExpander
            className="newsroom-section-rail__rotating"
            collapseOnAction
            label="Rotating"
            panelClassName="newsroom-section-rail__rotating-panel"
            panelDataAttributeName="data-newsroom-rotating-expander-panel"
            panelId="newsroom-rotating-expander-panel"
            panelInnerClassName="newsroom-section-rail__rotating-panel-inner newsroom-section-rail__canonical-list"
            toggleClassName="newsroom-section-rail__rotating-toggle"
            toggleDataAttributeName="data-newsroom-rotating-expander-toggle"
          >
            {rotatingSections.map((section) => (
              <Link
                className="newsroom-section-rail__link"
                data-newsroom-section-link={section.id}
                data-newsroom-section-type="rotating"
                data-newsroom-rotating-option={section.id}
                href={buildNewsroomSectionHref(section.id, demo)}
                key={section.id}
              >
                <span className="newsroom-section-rail__link-text">
                  <span>{section.title}</span>
                  <small>{displayNewsroomSectionShortTitle(section)}</small>
                </span>
              </Link>
            ))}
          </NewsroomExpander>
        ) : null}
      </div>
    </aside>
  );
}

function NewsroomExpander({
  children,
  className,
  collapseOnAction = false,
  defaultExpanded = false,
  label,
  panelClassName,
  panelDataAttributeName,
  panelId,
  panelInnerClassName,
  toggleClassName,
  toggleDataAttributeName,
}: {
  children: ReactNode;
  className?: string;
  collapseOnAction?: boolean;
  defaultExpanded?: boolean;
  label: string;
  panelClassName?: string;
  panelDataAttributeName?: string;
  panelId?: string;
  panelInnerClassName?: string;
  toggleClassName?: string;
  toggleDataAttributeName?: string;
}) {
  const generatedId = useId();
  const stablePanelId = useMemo(
    () => panelId ?? `newsroom-expander-panel-${generatedId.replace(/[:]/g, "")}`,
    [generatedId, panelId],
  );
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [shouldRenderPanel, setShouldRenderPanel] = useState(defaultExpanded);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLDivElement | null>(null);
  const toggleDataAttribute = useMemo(
    () => (toggleDataAttributeName ? { [toggleDataAttributeName]: true } : {}),
    [toggleDataAttributeName],
  );
  const panelDataAttribute = useMemo(
    () => (panelDataAttributeName ? { [panelDataAttributeName]: true } : {}),
    [panelDataAttributeName],
  );

  useEffect(() => {
    if (isExpanded) setShouldRenderPanel(true);
  }, [isExpanded]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    const inner = innerRef.current;
    if (!panel || !inner) return;

    gsap.killTweensOf([panel, inner]);

    if (!shouldRenderPanel) {
      panel.hidden = true;
      panel.style.height = "";
      panel.style.opacity = "";
      panel.style.overflow = "";
      panel.style.visibility = "";
      inner.style.opacity = "";
      inner.style.transform = "";
      return;
    }

    panel.hidden = false;
    const targetHeight = Math.max(inner.scrollHeight, 1);

    if (isExpanded) {
      gsap.set(panel, { autoAlpha: 0, display: "block", height: 0, overflow: "hidden" });
      gsap.set(inner, { autoAlpha: 0, y: -10 });
      gsap.to(panel, {
        autoAlpha: 1,
        duration: 0.3,
        ease: "power3.out",
        height: targetHeight,
        onComplete: () => {
          panel.style.height = "auto";
          panel.style.overflow = "visible";
        },
      });
      gsap.to(inner, {
        autoAlpha: 1,
        duration: 0.28,
        ease: "power3.out",
        y: 0,
      });
      return;
    }

    gsap.set(panel, {
      autoAlpha: 1,
      display: "block",
      height: panel.offsetHeight || targetHeight,
      overflow: "hidden",
    });
    gsap.to(inner, {
      autoAlpha: 0,
      duration: 0.18,
      ease: "power2.inOut",
      y: -8,
    });
    gsap.to(panel, {
      autoAlpha: 0,
      duration: 0.22,
      ease: "power2.inOut",
      height: 0,
      onComplete: () => {
        panel.hidden = true;
        panel.style.height = "";
        panel.style.opacity = "";
        panel.style.overflow = "";
        panel.style.visibility = "";
        inner.style.opacity = "";
        inner.style.transform = "";
        setShouldRenderPanel(false);
      },
    });
  }, [isExpanded, shouldRenderPanel]);

  return (
    <div className={className ?? ""}>
      <button
        type="button"
        className={toggleClassName ?? "newsroom-section-rail__rotating-toggle"}
        {...toggleDataAttribute}
        aria-expanded={isExpanded ? "true" : "false"}
        aria-controls={stablePanelId}
        onClick={() => setIsExpanded((current) => !current)}
      >
        <span className="newsroom-section-rail__rotating-toggle-label">{label}</span>
        <RotatingSectionTriangleIcon expanded={isExpanded} />
      </button>
      <div
        className={panelClassName ?? "newsroom-section-rail__rotating-panel"}
        {...panelDataAttribute}
        id={stablePanelId}
        ref={panelRef}
        aria-hidden={isExpanded ? "false" : "true"}
        hidden={!shouldRenderPanel}
        onClick={collapseOnAction ? (event) => {
          const target = event.target as HTMLElement | null;
          if (target?.closest("a,button,[role='menuitem']")) setIsExpanded(false);
        } : undefined}
      >
        <div className={panelInnerClassName ?? "newsroom-section-rail__rotating-panel-inner"} ref={innerRef}>
          {children}
        </div>
      </div>
    </div>
  );
}

function RotatingSectionTriangleIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      aria-hidden="true"
      className={`newsroom-section-rail__rotating-icon${expanded ? " newsroom-section-rail__rotating-icon--expanded" : ""}`}
      focusable="false"
      viewBox="0 0 10 10"
    >
      <path d="M7.5 1 2.5 5 7.5 9Z" fill="currentColor" />
    </svg>
  );
}

function DeepNewsroomSectionView({
  demo,
  disabled,
  onCreateInsight,
  section,
  sectionId,
  sectionsLoaded,
}: {
  demo: boolean;
  disabled: boolean;
  onCreateInsight: (target: InsightTarget, summary: string, body: string) => Promise<void>;
  section: NewsroomSectionRecord | null;
  sectionId: string;
  sectionsLoaded: boolean;
}) {
  const insightTarget = section ? insightTargetForNewsroomSection(section) : null;
  const insightComposer = useNewsroomInsightComposer(insightTarget, disabled, onCreateInsight);

  if (!section) {
    return (
      <section className="newsroom-deep-section" data-newsroom-deep-section-missing={sectionId}>
        <p className="story-label">Section</p>
        <h2>{sectionsLoaded ? "Section not found" : "Loading section"}</h2>
        <p>{sectionsLoaded ? "This section is not configured or is disabled." : "Loading the configured newsroom section."}</p>
      </section>
    );
  }

  const guidanceRows = [
    ["Assignment Guidance", section.assignmentGuidance],
    ["Kill Criteria", section.killCriteria],
    ["Visual Guidance", section.visualGuidance],
  ].filter((row): row is [string, string] => typeof row[1] === "string" && row[1].trim().length > 0);

  return (
    <section
      className="newsroom-deep-section"
      data-newsroom-deep-section={section.id}
      data-newsroom-section-type={formatNewsroomSectionTypeLabel(section.type).toLowerCase()}
    >
      <header className="newsroom-deep-section__header">
        <p className="story-label" data-newsroom-deep-section-eyebrow>Section</p>
        <h2 data-newsroom-deep-section-title>{section.title}</h2>
        <p>{displayNewsroomSectionShortTitle(section)}</p>
        <div className="newsroom-deep-section__header-actions">
          <button type="button" disabled={insightComposer.action.disabled} onClick={insightComposer.action.onSelect}>
            {insightComposer.loading ? "Saving Insight" : "Add Insight"}
          </button>
          <Link href={getNewsDeskTabHref("/newsroom", demo)}>Back to Newsroom</Link>
        </div>
      </header>
      {insightComposer.error ? <div className="category-steering-alert" role="status">{insightComposer.error}</div> : null}
      <div className="newsroom-deep-section__body">
        <article className="newsroom-deep-section__field newsroom-deep-section__field--lead">
          <p className="story-label">Mission</p>
          <p>{section.editorialMission}</p>
        </article>
        <article className="newsroom-deep-section__field newsroom-deep-section__field--lead">
          <p className="story-label">Policy</p>
          <p>{section.editorialPolicy}</p>
        </article>
        {guidanceRows.map(([label, value]) => (
          <article className="newsroom-deep-section__field" key={label}>
            <p className="story-label">{label}</p>
            <p>{value}</p>
          </article>
        ))}
      </div>
      {insightComposer.dialog}
    </section>
  );
}

function NewsroomOverviewSection({
  cards,
  detail,
  emptyLabel,
  error,
  isLoading,
  moreHref,
  sectionKey,
  title,
}: {
  cards: NewsroomCardRecord[];
  detail: string;
  emptyLabel: string;
  error: string | null;
  isLoading: boolean;
  moreHref: string;
  sectionKey: "messages" | "assignments" | "references";
  title: string;
}) {
  const headingId = `newsroom-overview-${sectionKey}`;
  return (
    <section
      className="newsroom-overview-section"
      data-newsroom-overview-section={sectionKey}
      aria-labelledby={headingId}
    >
      <header className="newsroom-overview-section__header">
        <div className="newsroom-overview-section__header-copy">
          <p className="story-label">Newsroom</p>
          <h2 id={headingId}>{title}</h2>
          <span>{detail}</span>
        </div>
        <Link data-newsroom-overview-more={sectionKey} href={moreHref}>More</Link>
      </header>
      {error ? (
        <div className="newsroom-overview-section__state" role="status">{error}</div>
      ) : isLoading && !cards.length ? (
        <div className="newsroom-overview-section__state" role="status">Loading recent records...</div>
      ) : cards.length ? (
        <div className="newsroom-overview-section__card-grid" data-newsroom-overview-card-grid>
          {cards.map((card) => {
            const span = card.span ?? "1x1";
            const templateRole = card.templateRole ?? "standard";
            return (
              <Link
                aria-label={card.ariaLabel}
                className={`newsroom-card newsroom-card--span-${span}`}
                data-newsroom-card
                data-newsroom-card-id={card.id}
                data-newsroom-card-span={span}
                data-newsroom-card-template-role={templateRole}
                data-newsroom-overview-section-card
                href={card.href ?? moreHref}
                key={card.id}
                {...card.dataAttributes}
              >
                <NewsroomCardContents card={card} />
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="newsroom-overview-section__state">{emptyLabel}</div>
      )}
    </section>
  );
}

function withNewsroomOverviewCardLayout(card: NewsroomCardRecord, index: number, href: string): NewsroomCardRecord {
  const template = resolveNewsroomCardTemplate({ mode: "overview", index });
  return {
    ...card,
    href,
    span: template.span,
    templateRole: template.role,
  };
}

function NewsroomCardContents({ card }: { card: NewsroomCardRecord }) {
  return (
    <>
      {card.kicker ? <span className="newsroom-card__kicker">{card.kicker}</span> : null}
      <strong className="newsroom-card__title">{card.title}</strong>
      {card.body ? <span className="newsroom-card__body">{card.body}</span> : null}
      {card.meta.length ? (
        <span className="newsroom-card__meta">
          {card.meta.map((entry, index) => (
            <span key={`${card.id}-meta-${index}`}>{entry}</span>
          ))}
        </span>
      ) : null}
      {card.stamp ? <span className="newsroom-card__stamp">{card.stamp}</span> : null}
    </>
  );
}

function AdministrationDeskView({
  actionState,
  administrationPanel,
  canManageUsers,
  disabled,
  doctrineCategories,
  doctrineDrafts,
  doctrineRecords,
  isDemo,
  mergeSelection,
  newsroomSections,
  onCancelMerge,
  onCategoryDoctrineSave,
  onConfirmMerge,
  onMergeReasonChange,
  onMergeRequest,
  onMergeTargetChange,
  onPanelChange,
  onPolicyChange,
  onPolicySave,
  onProcedureDefinitionSave,
  onProcedureRun,
  onProcedureVersionDraftSave,
  onProcedureVersionPublish,
  onSectionReorder,
  onSectionSave,
  onRoleAction,
  procedureRuns,
  procedureVersions,
  procedures,
  users,
}: {
  actionState: ActionState | null;
  administrationPanel: AdministrationPanel;
  canManageUsers: boolean;
  disabled: boolean;
  doctrineCategories: DoctrineCategory[];
  doctrineDrafts: DoctrineEditorState;
  doctrineRecords: DoctrineRecord[];
  isDemo: boolean;
  mergeSelection: MergeSelection | null;
  newsroomSections: NewsroomSectionRecord[];
  onCancelMerge: () => void;
  onCategoryDoctrineSave: (category: DoctrineCategory, kind: DoctrineKind, text: string) => void;
  onConfirmMerge: () => void;
  onMergeReasonChange: (reason: string) => void;
  onMergeRequest: (user: UserDirectoryEntry) => void;
  onMergeTargetChange: (targetUserProfileId: string) => void;
  onPanelChange: (panel: AdministrationPanel) => void;
  onPolicyChange: (kind: DoctrineKind, text: string) => void;
  onPolicySave: (kind: DoctrineKind) => void;
  onProcedureDefinitionSave: (input: {
    id?: string;
    procedureKey: string;
    title: string;
    category: string;
    description?: string;
    enabled: boolean;
  }) => void;
  onProcedureVersionDraftSave: (input: {
    id?: string;
    procedureId: string;
    procedureKey?: string;
    label?: string;
    tactusSource: string;
    parameterSchema: Record<string, unknown>;
    defaults?: Record<string, unknown>;
    changelog?: string;
  }) => void;
  onProcedureVersionPublish: (versionId: string) => void;
  onProcedureRun: (input: {
    procedureId?: string;
    procedureKey?: string;
    procedureVersionId?: string;
    title?: string;
    summary?: string;
    parameters?: Record<string, unknown>;
  }) => void;
  onSectionReorder: (nextOrder: NewsroomSectionRecord[]) => void;
  onSectionSave: (input: NewsroomSectionRecord, existingId?: string) => void;
  onRoleAction: (user: UserDirectoryEntry, role: string, action: UserRoleAction) => void;
  procedureRuns: ProcedureRunRecord[];
  procedureVersions: ProcedureVersionRecord[];
  procedures: ProcedureDefinitionRecord[];
  users: UserDirectoryEntry[];
}) {
  return (
    <div className="news-desk-columns news-desk-columns--administration" data-news-desk-section="administration">
      <div className="news-desk-main-column">
        <section className="category-steering-section category-steering-section--lead" aria-labelledby="newsroom-administration-title">
          <SectionHeader title="Administration" detail="Settings for users, policies, sections, and procedures" />
          <div className="news-desk-settings-shell">
            <nav className="news-desk-settings-nav" aria-label="Administration settings">
              <Link
                href={administrationPanelHref("users", isDemo)}
                data-news-desk-admin-nav="users"
                data-active={administrationPanel === "users" || undefined}
                onClick={() => onPanelChange("users")}
              >
                <strong>Users</strong>
                <span>Roles and identity merges</span>
              </Link>
              <Link
                href={administrationPanelHref("policies", isDemo)}
                data-news-desk-admin-nav="policies"
                data-active={administrationPanel === "policies" || undefined}
                onClick={() => onPanelChange("policies")}
              >
                <strong>Policies</strong>
                <span>Publication and category doctrine</span>
              </Link>
              <Link
                href={administrationPanelHref("sections", isDemo)}
                data-news-desk-admin-nav="sections"
                data-active={administrationPanel === "sections" || undefined}
                onClick={() => onPanelChange("sections")}
              >
                <strong>Sections</strong>
                <span>Canonical and floating newspaper sections</span>
              </Link>
              <Link
                href={administrationPanelHref("procedures", isDemo)}
                data-news-desk-admin-nav="procedures"
                data-active={administrationPanel === "procedures" || undefined}
                onClick={() => onPanelChange("procedures")}
              >
                <strong>Procedures</strong>
                <span>Procedure registry and versioned Tactus code</span>
              </Link>
            </nav>
            <div className="news-desk-settings-panel">
              {administrationPanel === "users" ? (
                <AdministrationUsersPanel
                  canManageUsers={canManageUsers}
                  disabled={disabled}
                  mergeSelection={mergeSelection}
                  onCancelMerge={onCancelMerge}
                  onConfirmMerge={onConfirmMerge}
                  onMergeReasonChange={onMergeReasonChange}
                  onMergeRequest={onMergeRequest}
                  onMergeTargetChange={onMergeTargetChange}
                  onRoleAction={onRoleAction}
                  users={users}
                />
              ) : null}
              {administrationPanel === "policies" ? (
                <AdministrationPoliciesPanel
                  actionState={actionState}
                  disabled={disabled}
                  doctrineCategories={doctrineCategories}
                  doctrineDrafts={doctrineDrafts}
                  doctrineRecords={doctrineRecords}
                  onCategoryDoctrineSave={onCategoryDoctrineSave}
                  onPolicyChange={onPolicyChange}
                  onPolicySave={onPolicySave}
                />
              ) : null}
              {administrationPanel === "sections" ? (
                <AdministrationSectionsPanel
                  actionState={actionState}
                  disabled={disabled}
                  sections={newsroomSections}
                  onReorder={onSectionReorder}
                  onSave={onSectionSave}
                />
              ) : null}
              {administrationPanel === "procedures" ? (
                <AdministrationProceduresPanel
                  actionState={actionState}
                  canManageUsers={canManageUsers}
                  disabled={disabled}
                  onProcedureDefinitionSave={onProcedureDefinitionSave}
                  onProcedureRun={onProcedureRun}
                  onProcedureVersionDraftSave={onProcedureVersionDraftSave}
                  onProcedureVersionPublish={onProcedureVersionPublish}
                  procedures={procedures}
                  procedureRuns={procedureRuns}
                  procedureVersions={procedureVersions}
                />
              ) : null}
            </div>
          </div>
        </section>
      </div>

    </div>
  );
}

function AdministrationUsersPanel({
  canManageUsers,
  disabled,
  mergeSelection,
  onCancelMerge,
  onConfirmMerge,
  onMergeReasonChange,
  onMergeRequest,
  onMergeTargetChange,
  users,
  onRoleAction,
}: {
  canManageUsers: boolean;
  disabled: boolean;
  mergeSelection: MergeSelection | null;
  onCancelMerge: () => void;
  onConfirmMerge: () => void;
  onMergeReasonChange: (reason: string) => void;
  onMergeRequest: (user: UserDirectoryEntry) => void;
  onMergeTargetChange: (targetUserProfileId: string) => void;
  users: UserDirectoryEntry[];
  onRoleAction: (user: UserDirectoryEntry, role: string, action: UserRoleAction) => void;
}) {
  return (
    <div data-news-desk-admin-panel="users">
      <SectionHeader title="User Directory" detail={canManageUsers ? `${users.length} mapped users` : "Admin role required"} />
      {!canManageUsers ? <div className="category-steering-alert">Only admins can list Cognito users or change editor/admin roles.</div> : null}
      <div className="news-desk-user-list">
        {users.length ? users.map((user) => (
          <UserDirectoryRow
            key={user.userProfileId ?? user.userSub ?? user.email ?? "unknown"}
            canManageUsers={canManageUsers}
            canMerge={users.length > 1}
            disabled={disabled}
            onMergeRequest={onMergeRequest}
            onRoleAction={onRoleAction}
            user={user}
          />
        )) : <EmptyRow label={canManageUsers ? "No users returned by the directory" : "Sign in as an admin to load user records"} />}
      </div>
      {mergeSelection ? (
        <UserMergePanel
          disabled={disabled}
          onCancel={onCancelMerge}
          onConfirm={onConfirmMerge}
          onReasonChange={onMergeReasonChange}
          onTargetChange={onMergeTargetChange}
          selection={mergeSelection}
          users={users}
        />
      ) : null}
    </div>
  );
}

function AssignmentCreationPanel({
  actionState,
  analysisProfiles,
  corpora,
  disabled,
  onClose,
  onCreateAssignment,
  onSubmitted,
}: {
  actionState: ActionState | null;
  analysisProfiles: AnalysisProfileSummary[];
  corpora: CategorySteeringCorpus[];
  disabled: boolean;
  onClose: () => void;
  onCreateAssignment: (profile: AnalysisProfileSummary, draft: AnalysisReindexDraft) => void;
  onSubmitted?: () => void;
}) {
  const [selectedProfileKey, setSelectedProfileKey] = useState(analysisProfiles[0]?.key ?? "");
  const selectedProfile = analysisProfiles.find((profile) => profile.key === selectedProfileKey) ?? analysisProfiles[0] ?? null;
  const [mode, setMode] = useState<AnalysisReindexMode>(() => normalizeAnalysisReindexMode(selectedProfile?.defaultMode));
  const [corpusKey, setCorpusKey] = useState(selectedProfile?.corpusKey ?? "");
  const [overrideText, setOverrideText] = useState("{}");
  const corpusKeyOptions = useMemo(() => {
    const keys = corpora
      .map((corpus) => analysisCorpusKeyFromRecord(corpus))
      .filter((entry): entry is string => Boolean(entry));
    keys.push(...analysisProfiles
      .map((profile) => profile.corpusKey)
      .filter((entry): entry is string => Boolean(entry)));
    if (corpusKey.trim()) keys.push(corpusKey.trim());
    return Array.from(new Set(keys));
  }, [analysisProfiles, corpora, corpusKey]);

  useEffect(() => {
    if (!analysisProfiles.length) {
      setSelectedProfileKey("");
      return;
    }
    if (!analysisProfiles.some((profile) => profile.key === selectedProfileKey)) {
      setSelectedProfileKey(analysisProfiles[0].key);
    }
  }, [analysisProfiles, selectedProfileKey]);

  useEffect(() => {
    if (!selectedProfile) return;
    setMode(normalizeAnalysisReindexMode(selectedProfile.defaultMode));
    setCorpusKey(selectedProfile.corpusKey ?? "");
    setOverrideText("{}");
  }, [selectedProfile]);

  const overrideParse = useMemo(
    () => parseAnalysisOverrideJson(overrideText, selectedProfile),
    [overrideText, selectedProfile],
  );
  const commandPlan = selectedProfile
    ? buildAnalysisCommandPlanPreview({ profile: selectedProfile, corpusKey, mode, overrides: overrideParse.value })
    : [];
  const destructivePlan = selectedProfile
    ? buildAnalysisDestructivePreview({ profile: selectedProfile, corpusKey, mode })
    : null;
  const profileStatus = selectedProfile ? actionState?.id?.includes(selectedProfile.key) ? actionState : actionState?.id?.startsWith("assignment-analysis-reindex") ? actionState : null : null;

  function submitAssignment() {
    if (!selectedProfile || overrideParse.error || !corpusKey.trim()) return;
    onCreateAssignment(selectedProfile, {
      corpusKey: corpusKey.trim(),
      mode,
      overrides: overrideParse.value,
    });
    onSubmitted?.();
  }

  return (
    <div data-news-desk-assignment-create-panel="analysis">
      {!analysisProfiles.length ? <EmptyRow label="No analysis profiles loaded from corpora/papyrus-analysis-profiles.yml." /> : null}
      {selectedProfile ? (
        <div className="news-desk-analysis-grid">
          <div className="news-desk-analysis-form">
            <label className="news-desk-doctrine-card__field">
              <span>Profile</span>
              <select
                disabled={disabled}
                onChange={(event) => setSelectedProfileKey(event.target.value)}
                value={selectedProfile.key}
              >
                {analysisProfiles.map((profile) => (
                  <option key={profile.key} value={profile.key}>{profile.title}</option>
                ))}
              </select>
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Corpus</span>
              <select
                disabled={disabled}
                onChange={(event) => setCorpusKey(event.target.value)}
                value={corpusKey}
              >
                {corpusKeyOptions.map((key) => (
                  <option key={key} value={key}>{formatAnalysisCorpusLabel(key, corpora)}</option>
                ))}
              </select>
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Re-index level</span>
              <select
                disabled={disabled}
                onChange={(event) => setMode(normalizeAnalysisReindexMode(event.target.value))}
                value={mode}
              >
                {ANALYSIS_REINDEX_MODES.map((entry) => (
                  <option key={entry} value={entry}>{formatAnalysisReindexModeLabel(entry)}</option>
                ))}
              </select>
            </label>
            <p className="news-desk-analysis-help">{analysisReindexModeHelp(mode)}</p>
            <label className="news-desk-doctrine-card__field">
              <span>Advanced parameter overrides</span>
              <textarea
                data-news-desk-analysis-overrides
                disabled={disabled}
                onChange={(event) => setOverrideText(event.target.value)}
                rows={8}
                value={overrideText}
              />
            </label>
            <p className="news-desk-analysis-help">Optional JSON only for the allowed knobs listed at right. Leave as {"{}"} to use the profile defaults.</p>
            {overrideParse.error ? <div className="category-steering-alert">{overrideParse.error}</div> : null}
            <div className="news-desk-doctrine-card__footer">
              <span>{selectedProfile.scope} / {selectedProfile.configurationName ?? selectedProfile.key}</span>
              <div className="news-desk-doctrine-card__actions">
                {profileStatus ? <span data-tone={profileStatus.tone}>{profileStatus.message}</span> : null}
                <button
                  type="button"
                  data-news-desk-analysis-create-assignment
                  disabled={disabled || Boolean(overrideParse.error) || !corpusKey.trim()}
                  onClick={submitAssignment}
                >
                  Create Assignment
                </button>
                <button type="button" onClick={onClose}>
                  Cancel
                </button>
              </div>
            </div>
          </div>

          <div className="news-desk-ledger-list">
            <article className="news-desk-ledger-item">
              <header>
                <strong>{selectedProfile.title}</strong>
                <span>{selectedProfile.scope}</span>
              </header>
              <p>{selectedProfile.description}</p>
              <dl>
                <div>
                  <dt>Default re-index level</dt>
                  <dd>{formatAnalysisReindexModeLabel(normalizeAnalysisReindexMode(selectedProfile.defaultMode))}</dd>
                </div>
                <div>
                  <dt>Classifier id</dt>
                  <dd>{selectedProfile.classifierId ?? "profile default"}</dd>
                </div>
                <div>
                  <dt>Expected outputs</dt>
                  <dd>{selectedProfile.expectedOutputs.join(" / ") || "not declared"}</dd>
                </div>
              </dl>
            </article>
            <article className="news-desk-ledger-item">
              <header>
                <strong>Allowed Overrides</strong>
                <span>{selectedProfile.allowedOverrides.length} keys</span>
              </header>
              <p>{selectedProfile.allowedOverrides.join(", ") || "No user overrides for this profile."}</p>
            </article>
            <article className="news-desk-ledger-item">
              <header>
                <strong>Command Preview</strong>
                <span>{commandPlan.length} command{commandPlan.length === 1 ? "" : "s"}</span>
              </header>
              {commandPlan.map((command) => (
                <pre key={command.label} className="news-desk-analysis-command">{command.executable} {command.args.join(" ")}</pre>
              ))}
            </article>
            {destructivePlan ? (
              <article className="news-desk-ledger-item">
                <header>
                  <strong>Destructive Plan</strong>
                  <span>{destructivePlan.executesNow ? "would execute now" : "dry-run only"}</span>
                </header>
                <p>{destructivePlan.summary}</p>
              </article>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AdministrationPoliciesPanel({
  actionState,
  disabled,
  doctrineCategories,
  doctrineDrafts,
  doctrineRecords,
  onCategoryDoctrineSave,
  onPolicyChange,
  onPolicySave,
}: {
  actionState: ActionState | null;
  disabled: boolean;
  doctrineCategories: DoctrineCategory[];
  doctrineDrafts: DoctrineEditorState;
  doctrineRecords: DoctrineRecord[];
  onCategoryDoctrineSave: (category: DoctrineCategory, kind: DoctrineKind, text: string) => void;
  onPolicyChange: (kind: DoctrineKind, text: string) => void;
  onPolicySave: (kind: DoctrineKind) => void;
}) {
  const sortedCategories = useMemo(
    () => [...doctrineCategories].sort((left, right) => compareDoctrineCategories(left, right)),
    [doctrineCategories],
  );
  const [selectedCategoryKey, setSelectedCategoryKey] = useState<string | null>(sortedCategories[0]?.categoryKey ?? null);
  const selectedCategory = sortedCategories.find((category) => category.categoryKey === selectedCategoryKey) ?? sortedCategories[0] ?? null;

  useEffect(() => {
    if (!sortedCategories.length) {
      setSelectedCategoryKey(null);
      return;
    }
    if (!sortedCategories.some((category) => category.categoryKey === selectedCategoryKey)) {
      setSelectedCategoryKey(sortedCategories[0].categoryKey);
    }
  }, [selectedCategoryKey, sortedCategories]);

  return (
    <div data-news-desk-admin-panel="policies">
      <SectionHeader title="Editorial Policies" detail="Publication defaults with optional category overrides" />
      <div className="news-desk-doctrine-list">
        {DOCTRINE_DEFINITIONS.map((definition) => {
          const record = doctrineRecords.find((entry) => entry.slug === definition.slug) ?? null;
          const statusId = definition.slug;
          const statusMessage = actionState?.id === statusId ? actionState : null;
          return (
            <DoctrineEditorCard
              key={definition.kind}
              body={doctrineDrafts[definition.kind]}
              definition={definition}
              disabled={disabled}
              record={record}
              statusMessage={statusMessage}
              onChange={onPolicyChange}
              onSave={onPolicySave}
            />
          );
        })}
      </div>

      <section className="category-steering-section news-desk-administration-category-doctrine" aria-labelledby="category-doctrine-title">
        <SectionHeader title="Topic and Subtopic Policies" detail={`${sortedCategories.length} accepted categories`} />
        <div className="news-desk-administration-category-layout">
          <div className="news-desk-administration-category-list" data-news-desk-policy-categories>
            {sortedCategories.length ? sortedCategories.map((category) => {
              const selected = selectedCategory?.categoryKey === category.categoryKey;
              return (
                <button
                  key={category.categoryKey}
                  type="button"
                  className="news-desk-administration-category-button"
                  data-selected={selected || undefined}
                  data-news-desk-policy-category={category.categoryKey}
                  onClick={() => setSelectedCategoryKey(category.categoryKey)}
                >
                  <span style={{ paddingLeft: `${Math.max(0, category.depth ?? 0) * 14}px` }}>
                    {category.displayName}
                  </span>
                  <small>{category.shortTitle ?? deriveShortTitle(category.displayName)}</small>
                </button>
              );
            }) : <EmptyRow label="No accepted categories are available." />}
          </div>
          <div className="news-desk-doctrine-list" data-news-desk-policy-editor>
            {selectedCategory ? (["mission", "policy"] as DoctrineKind[]).map((kind) => {
              const definition = buildCategoryDoctrineDefinition(selectedCategory, kind);
              const record = doctrineRecords.find((entry) => entry.slug === definition.slug) ?? null;
              return (
                <CategoryDoctrineEditorCard
                  key={definition.slug}
                  category={selectedCategory}
                  definition={definition}
                  disabled={disabled}
                  record={record}
                  statusMessage={actionState?.id === definition.slug ? actionState : null}
                  onSave={onCategoryDoctrineSave}
                />
              );
            }) : <EmptyRow label="Select a category to edit optional mission and policy overrides." />}
          </div>
        </div>
      </section>
    </div>
  );
}

function AdministrationSectionsPanel({
  actionState,
  disabled,
  sections,
  onReorder,
  onSave,
}: {
  actionState: ActionState | null;
  disabled: boolean;
  sections: NewsroomSectionRecord[];
  onReorder: (nextOrder: NewsroomSectionRecord[]) => void;
  onSave: (input: NewsroomSectionRecord, existingId?: string) => void;
}) {
  const sortedSections = useMemo(() => sortNewsroomSections(sections), [sections]);
  const canonicalSections = sortedSections.filter((section) => section.type === "canonical");
  const floatingSections = sortedSections.filter((section) => section.type === "floating" || section.type === "rotating");
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(sortedSections[0]?.id ?? null);
  const [newSection, setNewSection] = useState<NewsroomSectionRecord>(() => createEmptyNewsroomSectionDraft(sortedSections.length + 1));
  const selectedSection = sortedSections.find((section) => section.id === selectedSectionId) ?? sortedSections[0] ?? null;
  const [sectionDraft, setSectionDraft] = useState<NewsroomSectionRecord | null>(selectedSection ? { ...selectedSection } : null);

  useEffect(() => {
    if (!sortedSections.length) {
      setSelectedSectionId(null);
      setSectionDraft(null);
      return;
    }
    if (!sortedSections.some((section) => section.id === selectedSectionId)) {
      setSelectedSectionId(sortedSections[0].id);
      setSectionDraft({ ...sortedSections[0] });
      return;
    }
    const matching = sortedSections.find((section) => section.id === selectedSectionId);
    if (matching) setSectionDraft({ ...matching });
  }, [selectedSectionId, sortedSections]);

  useEffect(() => {
    setNewSection(createEmptyNewsroomSectionDraft(sortedSections.length + 1));
  }, [sortedSections.length]);

  function moveSelected(direction: -1 | 1) {
    if (!selectedSection) return;
    const index = sortedSections.findIndex((entry) => entry.id === selectedSection.id);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= sortedSections.length) return;
    const next = [...sortedSections];
    const [entry] = next.splice(index, 1);
    next.splice(targetIndex, 0, entry);
    onReorder(next);
  }

  function saveSelected() {
    if (!sectionDraft) return;
    const normalized = normalizeSectionDraft(sectionDraft, true);
    if (!normalized) return;
    onSave(normalized, sectionDraft.id);
  }

  function createNewSection() {
    const normalized = normalizeSectionDraft(newSection, false);
    if (!normalized) return;
    onSave(normalized);
    setNewSection(createEmptyNewsroomSectionDraft(sortedSections.length + 2));
  }

  return (
    <div data-news-desk-admin-panel="sections">
      <SectionHeader title="Newspaper Sections" detail={`${sortedSections.length} configured sections`} />
      <div className="news-desk-administration-category-layout">
        <div className="news-desk-administration-category-list" data-news-desk-section-list>
          {sortedSections.length ? (
            <>
              <p className="story-label">Canonical</p>
              {canonicalSections.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  className="news-desk-administration-category-button"
                  data-selected={selectedSection?.id === section.id || undefined}
                  data-news-desk-admin-section={section.id}
                  onClick={() => setSelectedSectionId(section.id)}
                >
                  <span>{section.title}</span>
                  <small>{displayNewsroomSectionShortTitle(section)} / {section.enabled ? "enabled" : "disabled"}</small>
                </button>
              ))}
              <p className="story-label">Floating</p>
              {floatingSections.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  className="news-desk-administration-category-button"
                  data-selected={selectedSection?.id === section.id || undefined}
                  data-news-desk-admin-section={section.id}
                  onClick={() => setSelectedSectionId(section.id)}
                >
                  <span>{section.title}</span>
                  <small>{displayNewsroomSectionShortTitle(section)} / {section.enabled ? "enabled" : "disabled"}</small>
                </button>
              ))}
            </>
          ) : <EmptyRow label="No sections configured yet." />}
        </div>
        <div className="news-desk-doctrine-list" data-news-desk-section-editor>
          {sectionDraft ? (
            <article className="news-desk-doctrine-card" data-news-desk-section-form={sectionDraft.id}>
              <header className="news-desk-doctrine-card__header">
                <div>
                  <p className="story-label">Section</p>
                  <h3>{sectionDraft.title}</h3>
                </div>
                <span>{sectionDraft.type}</span>
              </header>
              <NewsroomSectionEditorBody draft={sectionDraft} disabled={disabled} onChange={setSectionDraft} />
              <div className="news-desk-doctrine-card__footer">
                <span>Order: {sectionDraft.sortOrder}</span>
                <div className="news-desk-doctrine-card__actions">
                  <button type="button" data-news-desk-section-move="up" disabled={disabled || !selectedSection || sortedSections[0]?.id === selectedSection.id} onClick={() => moveSelected(-1)}>Move Up</button>
                  <button type="button" data-news-desk-section-move="down" disabled={disabled || !selectedSection || sortedSections[sortedSections.length - 1]?.id === selectedSection.id} onClick={() => moveSelected(1)}>Move Down</button>
                  <button type="button" data-news-desk-section-save={sectionDraft.id} disabled={disabled || !isSectionDraftValid(sectionDraft)} onClick={saveSelected}>Save</button>
                </div>
              </div>
            </article>
          ) : <EmptyRow label="Select a section to edit." />}
        </div>
      </div>

      <article className="news-desk-doctrine-card" data-news-desk-section-create>
        <header className="news-desk-doctrine-card__header">
          <div>
            <p className="story-label">Section</p>
            <h3>Create New Section</h3>
          </div>
          <span>Draft</span>
        </header>
        <NewsroomSectionEditorBody draft={newSection} disabled={disabled} onChange={setNewSection} />
        <div className="news-desk-doctrine-card__footer">
          <span>{newSection.type} / sort {newSection.sortOrder}</span>
          <div className="news-desk-doctrine-card__actions">
            <button type="button" data-news-desk-section-create-save disabled={disabled || !isSectionDraftValid(newSection)} onClick={createNewSection}>Create</button>
          </div>
        </div>
      </article>

      {actionState?.id?.startsWith("section-") || actionState?.id === "sections-reorder"
        ? <div className="category-steering-alert" data-tone={actionState.tone}>{actionState.message}</div>
        : null}
    </div>
  );
}

function NewsroomSectionEditorBody({
  draft,
  disabled,
  onChange,
}: {
  draft: NewsroomSectionRecord;
  disabled: boolean;
  onChange: (next: NewsroomSectionRecord) => void;
}) {
  return (
    <>
      <label className="news-desk-doctrine-card__field">
        <span>ID</span>
        <input
          data-news-desk-section-input="id"
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, id: safeSectionId(event.target.value) })}
          placeholder="history"
          value={draft.id}
        />
      </label>
      <label className="news-desk-doctrine-card__field">
        <span>Title</span>
        <input
          data-news-desk-section-input="title"
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, title: event.target.value })}
          placeholder="History"
          value={draft.title}
        />
      </label>
      <label className="news-desk-doctrine-card__field">
        <span>Type</span>
        <select
          data-news-desk-section-input="type"
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, type: event.target.value === "floating" ? "floating" : "canonical" })}
          value={draft.type}
        >
          <option value="canonical">canonical</option>
          <option value="floating">floating</option>
        </select>
      </label>
      <label className="news-desk-doctrine-card__field">
        <span>Editorial Mission</span>
        <textarea
          data-news-desk-section-input="mission"
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, editorialMission: event.target.value })}
          rows={3}
          value={draft.editorialMission}
        />
      </label>
      <label className="news-desk-doctrine-card__field">
        <span>Editorial Policy</span>
        <textarea
          data-news-desk-section-input="policy"
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, editorialPolicy: event.target.value })}
          rows={4}
          value={draft.editorialPolicy}
        />
      </label>
      <label className="news-desk-doctrine-card__field">
        <span>Enabled</span>
        <select
          data-news-desk-section-input="enabled"
          disabled={disabled}
          onChange={(event) => onChange({ ...draft, enabled: event.target.value === "true" })}
          value={String(draft.enabled)}
        >
          <option value="true">enabled</option>
          <option value="false">disabled</option>
        </select>
      </label>
      <details>
        <summary>Advanced fields</summary>
        <label className="news-desk-doctrine-card__field">
          <span>Short Title</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, shortTitle: event.target.value })}
            placeholder="Current Developments"
            value={draft.shortTitle}
          />
        </label>
        <label className="news-desk-doctrine-card__field">
          <span>Default Article Types (comma-separated)</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, defaultArticleTypes: parseCommaList(event.target.value) })}
            value={(draft.defaultArticleTypes ?? []).filter(Boolean).join(", ")}
          />
        </label>
        <label className="news-desk-doctrine-card__field">
          <span>Default Page Budget</span>
          <input
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, defaultPageBudget: parseOptionalInt(event.target.value) })}
            type="number"
            value={draft.defaultPageBudget ?? ""}
          />
        </label>
        <label className="news-desk-doctrine-card__field">
          <span>Assignment Guidance</span>
          <textarea disabled={disabled} onChange={(event) => onChange({ ...draft, assignmentGuidance: event.target.value || null })} rows={3} value={draft.assignmentGuidance ?? ""} />
        </label>
        <label className="news-desk-doctrine-card__field">
          <span>Kill Criteria</span>
          <textarea disabled={disabled} onChange={(event) => onChange({ ...draft, killCriteria: event.target.value || null })} rows={2} value={draft.killCriteria ?? ""} />
        </label>
        <label className="news-desk-doctrine-card__field">
          <span>Visual Guidance</span>
          <textarea disabled={disabled} onChange={(event) => onChange({ ...draft, visualGuidance: event.target.value || null })} rows={2} value={draft.visualGuidance ?? ""} />
        </label>
      </details>
    </>
  );
}

function DoctrineEditorCard({
  body,
  definition,
  disabled,
  record,
  statusMessage,
  onChange,
  onSave,
}: {
  body: string;
  definition: { kind: DoctrineKind; label: string; slug: string };
  disabled: boolean;
  record: DoctrineRecord | null;
  statusMessage: ActionState | null;
  onChange: (kind: DoctrineKind, text: string) => void;
  onSave: (kind: DoctrineKind) => void;
}) {
  const paragraphCount = doctrineTextToBody(body).length;
  return (
    <article className="news-desk-doctrine-card" data-news-desk-doctrine={definition.kind}>
      <header className="news-desk-doctrine-card__header">
        <div>
          <p className="story-label">Doctrine</p>
          <h3>{definition.label}</h3>
        </div>
        <span>{record ? "Saved record" : "Empty slot"}</span>
      </header>
      <label className="news-desk-doctrine-card__field">
        <span>{definition.label}</span>
        <textarea
          data-news-desk-doctrine-input={definition.kind}
          disabled={disabled}
          onChange={(event) => onChange(definition.kind, event.target.value)}
          placeholder={`Enter the ${definition.label.toLowerCase()}.`}
          value={body}
        />
      </label>
      <div className="news-desk-doctrine-card__footer">
        <span>{paragraphCount} paragraph{paragraphCount === 1 ? "" : "s"}</span>
        <div className="news-desk-doctrine-card__actions">
          {statusMessage ? <span data-tone={statusMessage.tone}>{statusMessage.message}</span> : null}
          <button
            type="button"
            data-news-desk-doctrine-save={definition.kind}
            disabled={disabled}
            onClick={() => onSave(definition.kind)}
          >
            Save
          </button>
        </div>
      </div>
    </article>
  );
}

function AdministrationProceduresPanel({
  actionState,
  canManageUsers,
  disabled,
  onProcedureDefinitionSave,
  onProcedureRun,
  onProcedureVersionDraftSave,
  onProcedureVersionPublish,
  procedures,
  procedureRuns,
  procedureVersions,
}: {
  actionState: ActionState | null;
  canManageUsers: boolean;
  disabled: boolean;
  onProcedureDefinitionSave: (input: {
    id?: string;
    procedureKey: string;
    title: string;
    category: string;
    description?: string;
    enabled: boolean;
  }) => void;
  onProcedureVersionDraftSave: (input: {
    id?: string;
    procedureId: string;
    procedureKey?: string;
    label?: string;
    tactusSource: string;
    parameterSchema: Record<string, unknown>;
    defaults?: Record<string, unknown>;
    changelog?: string;
  }) => void;
  onProcedureVersionPublish: (versionId: string) => void;
  onProcedureRun: (input: {
    procedureId?: string;
    procedureKey?: string;
    procedureVersionId?: string;
    title?: string;
    summary?: string;
    parameters?: Record<string, unknown>;
  }) => void;
  procedures: ProcedureDefinitionRecord[];
  procedureVersions: ProcedureVersionRecord[];
  procedureRuns: ProcedureRunRecord[];
}) {
  type ProcedureDefinitionPanelRecord = ProcedureDefinitionRecord & {
    currentVersion?: ProcedureVersionRecord | null;
    versions?: ProcedureVersionRecord[] | null;
  };
  const sortedProcedures = useMemo(
    () => [...(procedures as ProcedureDefinitionPanelRecord[])].sort((left, right) => String(left.procedureKey).localeCompare(String(right.procedureKey))),
    [procedures],
  );
  const [selectedProcedureId, setSelectedProcedureId] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState(false);
  const selectedProcedure = sortedProcedures.find((entry) => entry.id === selectedProcedureId) ?? null;
  const showEditor = createMode || Boolean(selectedProcedure);
  const versions = useMemo(() => {
    if (!selectedProcedure) return [];
    const listedVersions = procedureVersions
      .filter((entry) => entry.procedureId === selectedProcedure.id)
      .sort((left, right) => (right.versionNumber ?? 0) - (left.versionNumber ?? 0));
    if (listedVersions.length > 0) return listedVersions;
    const embeddedVersions = Array.isArray(selectedProcedure.versions)
      ? selectedProcedure.versions.filter((entry): entry is ProcedureVersionRecord => Boolean(entry?.id && entry?.procedureId))
      : [];
    return embeddedVersions.sort((left, right) => (right.versionNumber ?? 0) - (left.versionNumber ?? 0));
  }, [procedureVersions, selectedProcedure]);
  const currentVersion = versions.find((entry) => entry.isCurrent) ?? versions[0] ?? null;
  const fallbackCurrentVersion = currentVersion
    ?? (selectedProcedure?.currentVersion && selectedProcedure.currentVersion.id ? selectedProcedure.currentVersion : null);
  const runs = useMemo(
    () => (selectedProcedure
      ? procedureRuns.filter((entry) => entry.procedureId === selectedProcedure.id).sort((left, right) => String(right.requestedAt ?? "").localeCompare(String(left.requestedAt ?? ""))).slice(0, 12)
      : []),
    [procedureRuns, selectedProcedure],
  );

  const [definitionDraft, setDefinitionDraft] = useState({
    procedureKey: "",
    title: "",
    category: "ingestion",
    description: "",
    enabled: true,
  });
  const [versionLabel, setVersionLabel] = useState(fallbackCurrentVersion?.label ?? "");
  const [versionSource, setVersionSource] = useState(fallbackCurrentVersion?.tactusSource ?? "-- Write Tactus/Lua procedure body here");
  const [parameterSchemaText, setParameterSchemaText] = useState(
    stringifyUiJson(fallbackCurrentVersion?.parameterSchema ?? {
      type: "object",
      required: [],
      properties: {},
    }),
  );
  const [defaultsText, setDefaultsText] = useState(stringifyUiJson(fallbackCurrentVersion?.defaults ?? {}));
  const [runInputText, setRunInputText] = useState(stringifyUiJson(fallbackCurrentVersion?.defaults ?? {}));

  useEffect(() => {
    if (createMode) {
      setDefinitionDraft({
        procedureKey: "",
        title: "",
        category: "ingestion",
        description: "",
        enabled: true,
      });
      return;
    }
    setDefinitionDraft({
      procedureKey: selectedProcedure?.procedureKey ?? "",
      title: selectedProcedure?.title ?? "",
      category: selectedProcedure?.category ?? "ingestion",
      description: selectedProcedure?.description ?? "",
      enabled: selectedProcedure?.enabled ?? true,
    });
  }, [createMode, selectedProcedure?.category, selectedProcedure?.description, selectedProcedure?.enabled, selectedProcedure?.procedureKey, selectedProcedure?.title]);

  useEffect(() => {
    setVersionLabel(fallbackCurrentVersion?.label ?? "");
    setVersionSource(fallbackCurrentVersion?.tactusSource ?? "-- Write Tactus/Lua procedure body here");
    setParameterSchemaText(
      stringifyUiJson(fallbackCurrentVersion?.parameterSchema ?? {
        type: "object",
        required: [],
        properties: {},
      }),
    );
    setDefaultsText(stringifyUiJson(fallbackCurrentVersion?.defaults ?? {}));
    setRunInputText(stringifyUiJson(fallbackCurrentVersion?.defaults ?? {}));
  }, [fallbackCurrentVersion?.defaults, fallbackCurrentVersion?.label, fallbackCurrentVersion?.parameterSchema, fallbackCurrentVersion?.tactusSource]);

  const parsedSchema = parseUiJsonRecord(parameterSchemaText);
  const parsedDefaults = parseUiJsonRecord(defaultsText);
  const parsedRunInput = parseUiJsonRecord(runInputText);

  function saveDefinition() {
    if (!definitionDraft.procedureKey.trim() || !definitionDraft.title.trim()) return;
    onProcedureDefinitionSave({
      id: selectedProcedure?.id,
      procedureKey: definitionDraft.procedureKey.trim(),
      title: definitionDraft.title.trim(),
      category: definitionDraft.category.trim() || "ingestion",
      description: definitionDraft.description.trim() || undefined,
      enabled: Boolean(definitionDraft.enabled),
    });
  }

  function saveVersionDraft() {
    if (!selectedProcedure) return;
    if (!versionSource.trim()) return;
    if (parsedSchema.error || parsedDefaults.error) return;
    onProcedureVersionDraftSave({
      procedureId: selectedProcedure.id,
      procedureKey: selectedProcedure.procedureKey,
      label: versionLabel.trim() || undefined,
      tactusSource: versionSource,
      parameterSchema: parsedSchema.value ?? {},
      defaults: parsedDefaults.value ?? {},
    });
  }

  function runNow() {
    if (!selectedProcedure) return;
    if (parsedRunInput.error) return;
    onProcedureRun({
      procedureId: selectedProcedure.id,
      procedureKey: selectedProcedure.procedureKey,
      procedureVersionId: currentVersion?.id ?? selectedProcedure.currentVersionId ?? undefined,
      title: `Run ${selectedProcedure.title}`,
      summary: "Triggered from Newsroom Administration procedures panel.",
      parameters: parsedRunInput.value ?? {},
    });
  }

  return (
    <div data-news-desk-admin-panel="procedures">
      <SectionHeader title="Procedure Registry" detail={canManageUsers ? `${procedures.length} procedure definitions` : "Admin role required"} />
      {!canManageUsers ? <div className="category-steering-alert">Only admins can manage procedures.</div> : null}
      <div className="news-desk-administration-category-layout">
        <div className="news-desk-administration-category-list">
          <button
            type="button"
            className="news-desk-primary-action-button"
            disabled={disabled || !canManageUsers}
            onClick={() => {
              setCreateMode(true);
              setSelectedProcedureId(null);
            }}
          >
            Create Procedure
          </button>
          {sortedProcedures.length ? sortedProcedures.map((procedure) => (
            <button
              key={procedure.id}
              type="button"
              className="news-desk-administration-category-button"
              data-selected={selectedProcedure?.id === procedure.id || undefined}
              onClick={() => {
                setCreateMode(false);
                setSelectedProcedureId(procedure.id);
              }}
            >
              <span>{procedure.title}</span>
              <small>{procedure.procedureKey} / {procedure.enabled ? "enabled" : "disabled"}</small>
            </button>
          )) : <EmptyRow label="No procedures yet. Click Create Procedure to start." />}
        </div>
        <div className="news-desk-doctrine-list">
          {!showEditor ? <EmptyRow label="Select a procedure row on the left (or choose Create Procedure) to open the editor and Tactus source." /> : null}
          {showEditor ? (
            <>
          <article className="news-desk-doctrine-card">
            <h3>Definition</h3>
            <label className="news-desk-doctrine-card__field">
              <span>Procedure Key</span>
              <input
                value={definitionDraft.procedureKey}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setDefinitionDraft((current) => ({ ...current, procedureKey: event.target.value }))}
              />
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Title</span>
              <input
                value={definitionDraft.title}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setDefinitionDraft((current) => ({ ...current, title: event.target.value }))}
              />
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Category</span>
              <input
                value={definitionDraft.category}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setDefinitionDraft((current) => ({ ...current, category: event.target.value }))}
              />
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Description</span>
              <textarea
                rows={3}
                value={definitionDraft.description}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setDefinitionDraft((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Enabled</span>
              <input
                type="checkbox"
                checked={definitionDraft.enabled}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setDefinitionDraft((current) => ({ ...current, enabled: event.target.checked }))}
              />
            </label>
            <div className="news-desk-doctrine-card__footer">
              <div className="news-desk-doctrine-card__actions">
                <button type="button" disabled={disabled || !canManageUsers} onClick={saveDefinition}>
                  Save Definition
                </button>
              </div>
            </div>
          </article>

          <article className="news-desk-doctrine-card">
            <h3>Version Draft</h3>
            <label className="news-desk-doctrine-card__field">
              <span>Label</span>
              <input
                value={versionLabel}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setVersionLabel(event.target.value)}
              />
            </label>
            <label className="news-desk-doctrine-card__field">
              <span>Parameter JSON Schema</span>
              <textarea
                rows={8}
                value={parameterSchemaText}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setParameterSchemaText(event.target.value)}
              />
            </label>
            {parsedSchema.error ? <div className="category-steering-alert">{parsedSchema.error}</div> : null}
            <label className="news-desk-doctrine-card__field">
              <span>Defaults JSON</span>
              <textarea
                rows={5}
                value={defaultsText}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setDefaultsText(event.target.value)}
              />
            </label>
            {parsedDefaults.error ? <div className="category-steering-alert">{parsedDefaults.error}</div> : null}
            <label className="news-desk-doctrine-card__field">
              <span>Tactus/Lua Source</span>
              <textarea
                rows={12}
                value={versionSource}
                disabled={disabled || !canManageUsers}
                onChange={(event) => setVersionSource(event.target.value)}
              />
            </label>
            <div className="news-desk-doctrine-card__footer">
              <div className="news-desk-doctrine-card__actions">
                <button type="button" disabled={disabled || !canManageUsers || !selectedProcedure} onClick={saveVersionDraft}>
                  Save Draft Version
                </button>
                <button
                  type="button"
                  disabled={disabled || !canManageUsers || !currentVersion}
                  onClick={() => currentVersion && onProcedureVersionPublish(currentVersion.id)}
                >
                  Publish Current Version
                </button>
              </div>
            </div>
          </article>

          <article className="news-desk-doctrine-card">
            <h3>Run Procedure</h3>
            <label className="news-desk-doctrine-card__field">
              <span>Input Parameters (JSON)</span>
              <textarea
                rows={8}
                value={runInputText}
                disabled={disabled || !selectedProcedure}
                onChange={(event) => setRunInputText(event.target.value)}
              />
            </label>
            {parsedRunInput.error ? <div className="category-steering-alert">{parsedRunInput.error}</div> : null}
            <div className="news-desk-doctrine-card__footer">
              <span>{currentVersion ? `v${currentVersion.versionNumber} (${currentVersion.status})` : "No version selected"}</span>
              <div className="news-desk-doctrine-card__actions">
                <button type="button" disabled={disabled || !selectedProcedure || Boolean(parsedRunInput.error)} onClick={runNow}>
                  Run Now
                </button>
              </div>
            </div>
          </article>

          <article className="news-desk-ledger-item">
            <header>
              <strong>Recent Runs</strong>
              <span>{runs.length}</span>
            </header>
            {runs.length ? (
              <dl>
                {runs.map((run) => (
                  <div key={run.id}>
                    <dt>{run.runStatus}</dt>
                    <dd>{run.requestedAt ?? "-"} / attempt {run.attempt ?? 1}</dd>
                  </div>
                ))}
              </dl>
            ) : <EmptyRow label="No runs for this procedure yet." />}
          </article>
          {actionState?.id?.startsWith("procedure-") ? (
            <div className="category-steering-alert" data-tone={actionState.tone}>{actionState.message}</div>
          ) : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function parseUiJsonRecord(value: string): { value: Record<string, unknown> | null; error: string | null } {
  const text = value.trim();
  if (!text) return { value: {}, error: null };
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, error: "Expected a JSON object." };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch (error) {
    return { value: null, error: error instanceof Error ? error.message : "Invalid JSON." };
  }
}

function stringifyUiJson(value: unknown): string {
  try {
    return `${JSON.stringify(value ?? {}, null, 2)}\n`;
  } catch {
    return "{}\n";
  }
}

function UserDirectoryRow({
  canManageUsers,
  canMerge,
  disabled,
  onMergeRequest,
  user,
  onRoleAction,
}: {
  canManageUsers: boolean;
  canMerge: boolean;
  disabled: boolean;
  onMergeRequest: (user: UserDirectoryEntry) => void;
  user: UserDirectoryEntry;
  onRoleAction: (user: UserDirectoryEntry, role: string, action: UserRoleAction) => void;
}) {
  const activeRoles = new Set(compactArray(user.activeRoles));
  const label = user.displayName ?? user.email ?? user.username ?? user.userSub ?? "Unknown user";
  const identityCount = user.identities.length;
  return (
    <article className="news-desk-user-row" data-news-desk-user={user.userProfileId ?? user.userSub ?? label}>
      <div>
        <header>
          <strong>{label}</strong>
          <span>{compactArray(user.activeRoles).join(" / ") || "reader"}</span>
        </header>
        <p>{user.email ?? "No email"} / {user.provider ?? "provider unknown"} / {user.cognitoStatus ?? "no Cognito status"} / {identityCount} {identityCount === 1 ? "identity" : "identities"}</p>
        <div className="news-desk-chip-row">
          {user.identities.length ? user.identities.map((identity) => (
            <span key={identity.id}>{identity.email ?? identity.cognitoSub} ({identity.status})</span>
          )) : <span>No linked identity row</span>}
        </div>
      </div>
      <div className="news-desk-user-row__actions">
        {["editor", "admin"].map((role) => {
          const active = activeRoles.has(role);
          return (
            <button
              key={role}
              type="button"
              disabled={disabled || !canManageUsers}
              onClick={() => onRoleAction(user, role, active ? "revoke" : "grant")}
            >
              {active ? `Revoke ${role}` : `Make ${role}`}
            </button>
          );
        })}
        <button
          type="button"
          disabled={disabled || !canManageUsers || !canMerge}
          onClick={() => onMergeRequest(user)}
        >
          Merge
        </button>
      </div>
    </article>
  );
}

function UserMergePanel({
  disabled,
  selection,
  users,
  onCancel,
  onConfirm,
  onReasonChange,
  onTargetChange,
}: {
  disabled: boolean;
  selection: MergeSelection;
  users: UserDirectoryEntry[];
  onCancel: () => void;
  onConfirm: () => void;
  onReasonChange: (reason: string) => void;
  onTargetChange: (targetUserKey: string) => void;
}) {
  const source = selection.source;
  const sourceKey = getUserDirectoryEntryKey(source);
  const targetOptions = users.filter((user) => getUserDirectoryEntryKey(user) !== sourceKey);
  const target = targetOptions.find((user) => getUserDirectoryEntryKey(user) === selection.targetUserKey) ?? null;
  return (
    <section className="category-steering-section news-desk-merge-panel" aria-labelledby="user-merge-title" data-news-desk-user-merge-panel="true">
      <SectionHeader title="Merge Users" detail="Identity repair" />
      <div className="category-steering-revision-panel">
        {selection.notice ? <p>{selection.notice}</p> : null}
        <label>
          <span>Source</span>
          <strong>{formatUserLabel(source)}</strong>
        </label>
        <label>
          <span>Target user</span>
          <select
            data-news-desk-merge-target
            disabled={disabled}
            value={selection.targetUserKey}
            onChange={(event) => onTargetChange(event.target.value)}
          >
            <option value="">Choose target user</option>
            {targetOptions.map((user) => (
              <option key={getUserDirectoryEntryKey(user)} value={getUserDirectoryEntryKey(user)}>
                {formatUserLabel(user)}{user.userProfileId ? "" : " (create profile)"}
              </option>
            ))}
          </select>
        </label>
        {!targetOptions.length ? (
          <p>No other user is available as a merge target.</p>
        ) : null}
        <label>
          <span>Reason</span>
          <textarea
            data-news-desk-merge-reason
            disabled={disabled}
            placeholder="Same human account"
            rows={3}
            value={selection.reason}
            onChange={(event) => onReasonChange(event.target.value)}
          />
        </label>
      </div>
      <div className="news-desk-merge-preview">
        <UserMergeIdentityBlock title="Source identities" user={source} />
        {target ? <UserMergeIdentityBlock title="Target identities" user={target} /> : null}
      </div>
      <div className="news-desk-user-row__actions">
        <button type="button" data-news-desk-merge-confirm disabled={disabled || !selection.targetUserKey} onClick={onConfirm}>Confirm Merge</button>
        <button type="button" disabled={disabled} onClick={onCancel}>Cancel</button>
      </div>
    </section>
  );
}

function UserMergeIdentityBlock({ title, user }: { title: string; user: UserDirectoryEntry }) {
  const fallback = user.userSub ?? user.email ?? "No linked identity row";
  return (
    <div>
      <p className="story-label">{title}</p>
      <div className="news-desk-chip-row">
        {user.identities.length ? user.identities.map((identity) => (
          <span key={identity.id}>{identity.email ?? identity.cognitoSub} ({identity.status})</span>
        )) : <span>{fallback}</span>}
      </div>
    </div>
  );
}

function DesksDeskView({
  assignments,
  categoryByUid,
  categoryNodes,
  disabled,
  doctrineRecords,
  graph,
  initialCategoryLineageId,
  isDemo,
  onCategorySave,
  onDeskDoctrineSave,
  rootCategories,
  statusMessage,
}: {
  assignments: AssignmentRecord[];
  categoryByUid: Map<string, CategorySteeringCategory>;
  categoryNodes: CategorySteeringCategoryTreeNode[];
  disabled: boolean;
  doctrineRecords: DoctrineRecord[];
  graph: SemanticGraph;
  initialCategoryLineageId?: string | null;
  isDemo: boolean;
  onCategorySave: (category: CategorySteeringCategory, update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">) => void;
  onDeskDoctrineSave: (category: DoctrineCategory, kind: DoctrineKind, text: string) => void;
  rootCategories: CategorySteeringCategory[];
  statusMessage: ActionState | null;
}) {
  const roots = buildCanonicalTopicRoots(rootCategories, categoryNodes, []);
  const initialRootKey = selectInitialRootKey(roots, initialCategoryLineageId);
  const [selectedRootKey, setSelectedRootKey] = useState<string | null>(initialRootKey);
  const selectedRoot = roots.find((root) => root.category.categoryKey === selectedRootKey) ?? roots[0] ?? null;

  useEffect(() => {
    if (!roots.length) {
      setSelectedRootKey(null);
      return;
    }
    const nextRootKey = selectedRoot?.category.categoryKey ?? initialRootKey ?? roots[0].category.categoryKey;
    if (selectedRootKey !== nextRootKey) setSelectedRootKey(nextRootKey);
  }, [initialRootKey, roots, selectedRoot, selectedRootKey]);

  return (
    <div className="news-desk-columns" data-news-desk-section="desks">
      <div className="news-desk-main-column">
        <section className="category-steering-section category-steering-section--lead" aria-labelledby="newsroom-desks-title">
          <SectionHeader title="News Desks" detail={`${roots.length} root topic desks`} />
          <div className="news-desk-desk-list">
            {roots.length ? roots.map((root) => {
              const rootNode = root.node ?? categoryToCategoryTreeNode(root.category);
              const rootContext = buildTopicDrilldownContext(root, rootNode, categoryByUid);
              const referenceCount = referencesForCategoryContext(graph, rootContext).length;
              const assignmentCount = countAssignmentsForDesk(assignments, graph, rootNode, root.subcategorys);
              const doctrineStatus = deskDoctrineStatus(root.category, doctrineRecords);
              const selected = selectedRoot?.category.categoryKey === root.category.categoryKey;
              return (
                <Link
                  className="news-desk-desk-card"
                  data-news-desk-card={root.category.categoryKey}
                  data-selected={selected || undefined}
                  href={getNewsDeskTabHref(`/newsroom/desks/${encodeURIComponent(root.category.categoryKey)}`, isDemo)}
                  key={root.category.categoryKey}
                  onClick={() => setSelectedRootKey(root.category.categoryKey)}
                >
                  <span>{rootNode.shortTitle ?? deriveShortTitle(rootNode.displayName)}</span>
                  <strong>{rootNode.displayName}</strong>
                  <p>{rootNode.description ?? "No desk description yet."}</p>
                  <small>{referenceCount} refs / {assignmentCount} assignments / {root.subcategorys.length} subtopics / {doctrineStatus.savedCount} of 2 doctrine slots</small>
                </Link>
              );
            }) : <EmptyRow label="No root topic desks are available in the canonical category set" />}
          </div>
        </section>

        {selectedRoot ? (
          <DeskDetailPanel
            assignments={assignments}
            categoryByUid={categoryByUid}
            disabled={disabled}
            doctrineRecords={doctrineRecords}
            graph={graph}
            onCategorySave={onCategorySave}
            onDeskDoctrineSave={onDeskDoctrineSave}
            root={selectedRoot}
            statusMessage={statusMessage}
          />
        ) : null}
      </div>

      <aside className="news-desk-rail-column">
        <section className="category-steering-section" aria-labelledby="desk-index-notes-title">
          <SectionHeader title="Desk Rules" detail="Root topics only" />
          <div className="news-desk-ledger-list">
            <article className="news-desk-ledger-item">
              <header>
                <strong>Desk Identity</strong>
                <span>Category</span>
              </header>
              <p>Official name, short title, subtitle, and description stay on the accepted root Category record.</p>
            </article>
            <article className="news-desk-ledger-item">
              <header>
                <strong>Desk Doctrine</strong>
                <span>Private Item</span>
              </header>
              <p>Mission and policies are private doctrine Items tied to the root category lineage.</p>
            </article>
            <article className="news-desk-ledger-item">
              <header>
                <strong>Subtopics</strong>
                <span>Optional overrides</span>
              </header>
              <p>Topic and subtopic doctrine can now be optionally set in Administration policies.</p>
            </article>
          </div>
        </section>
      </aside>
    </div>
  );
}

function DeskDetailPanel({
  assignments,
  categoryByUid,
  disabled,
  doctrineRecords,
  graph,
  onCategorySave,
  onDeskDoctrineSave,
  root,
  statusMessage,
}: {
  assignments: AssignmentRecord[];
  categoryByUid: Map<string, CategorySteeringCategory>;
  disabled: boolean;
  doctrineRecords: DoctrineRecord[];
  graph: SemanticGraph;
  onCategorySave: (category: CategorySteeringCategory, update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">) => void;
  onDeskDoctrineSave: (category: DoctrineCategory, kind: DoctrineKind, text: string) => void;
  root: CanonicalTopicRoot;
  statusMessage: ActionState | null;
}) {
  const rootNode = root.node ?? categoryToCategoryTreeNode(root.category);
  const rootContext = buildTopicDrilldownContext(root, rootNode, categoryByUid);
  const referenceCount = referencesForCategoryContext(graph, rootContext).length;
  const assignmentCount = countAssignmentsForDesk(assignments, graph, rootNode, root.subcategorys);
  const doctrineStatus = deskDoctrineStatus(root.category, doctrineRecords);

  return (
    <section className="category-steering-section news-desk-desk-detail" aria-labelledby="selected-desk-title">
      <header className="news-desk-topic-detail__header">
        <div>
          <p className="story-label">News Desk</p>
          <h3 id="selected-desk-title">{rootNode.displayName}</h3>
          <span>{rootNode.shortTitle ?? deriveShortTitle(rootNode.displayName)}</span>
        </div>
        <dl>
          <div>
            <dt>References</dt>
            <dd>{referenceCount}</dd>
          </div>
          <div>
            <dt>Assignments</dt>
            <dd>{assignmentCount}</dd>
          </div>
          <div>
            <dt>Subtopics</dt>
            <dd>{root.subcategorys.length}</dd>
          </div>
          <div>
            <dt>Doctrine</dt>
            <dd>{doctrineStatus.savedCount}/2</dd>
          </div>
        </dl>
      </header>

      <div className="news-desk-desk-detail__grid">
        <CategoryEditor category={root.category} disabled={disabled} onSave={onCategorySave} />
        <div className="news-desk-doctrine-list">
          {(["mission", "policy"] as DoctrineKind[]).map((kind) => {
            const definition = buildCategoryDoctrineDefinition(root.category, kind);
            const record = doctrineRecords.find((entry) => entry.slug === definition.slug) ?? null;
            return (
              <CategoryDoctrineEditorCard
                key={definition.slug}
                category={root.category}
                definition={definition}
                disabled={disabled}
                record={record}
                statusMessage={statusMessage?.id === definition.slug ? statusMessage : null}
                onSave={onDeskDoctrineSave}
              />
            );
          })}
        </div>
      </div>

      <div className="news-desk-desk-subtopics" aria-label={`${rootNode.displayName} inherited subtopics`}>
        <p className="category-steering-subcategory-list__label">Inherited Subtopics</p>
        <div className="news-desk-chip-row">
          {root.subcategorys.length ? root.subcategorys.map((subcategory) => (
            <span key={subcategory.id}>{subcategory.shortTitle ?? deriveShortTitle(subcategory.displayName)}</span>
          )) : <span>No accepted child topics</span>}
        </div>
      </div>
    </section>
  );
}

function CategoryDoctrineEditorCard({
  category,
  definition,
  disabled,
  record,
  statusMessage,
  onSave,
}: {
  category: DoctrineCategory;
  definition: { kind: DoctrineKind; label: string; slug: string };
  disabled: boolean;
  record: DoctrineRecord | null;
  statusMessage: ActionState | null;
  onSave: (category: DoctrineCategory, kind: DoctrineKind, text: string) => void;
}) {
  const [body, setBody] = useState(() => doctrineBodyToText(record?.body));
  const paragraphCount = doctrineTextToBody(body).length;

  useEffect(() => {
    setBody(doctrineBodyToText(record?.body));
  }, [definition.slug, record?.id, record?.updatedAt, record?.body]);

  return (
    <article className="news-desk-doctrine-card" data-news-desk-doctrine={definition.slug}>
      <header className="news-desk-doctrine-card__header">
        <div>
          <p className="story-label">Desk Doctrine</p>
          <h3>{definition.label}</h3>
        </div>
        <span>{record ? "Saved record" : "Empty slot"}</span>
      </header>
      <label className="news-desk-doctrine-card__field">
        <span>{definition.label}</span>
        <textarea
          data-news-desk-doctrine-input={definition.slug}
          disabled={disabled}
          onChange={(event) => setBody(event.target.value)}
          placeholder={`Enter the ${category.displayName} ${definition.label.toLowerCase()}.`}
          value={body}
        />
      </label>
      <div className="news-desk-doctrine-card__footer">
        <span>{paragraphCount} paragraph{paragraphCount === 1 ? "" : "s"}</span>
        <div className="news-desk-doctrine-card__actions">
          {statusMessage ? <span data-tone={statusMessage.tone}>{statusMessage.message}</span> : null}
          <button
            type="button"
            data-news-desk-doctrine-save={definition.slug}
            disabled={disabled}
            onClick={() => onSave(category, definition.kind, body)}
          >
            Save
          </button>
        </div>
      </div>
    </article>
  );
}

function TopicsDeskView({
  activeCategoryTree,
  activeCategorySet,
  analysisProfiles,
  canonicalCategorys,
  categorySets,
  categorys,
  categoryByUid,
  categoryKeywords,
  categoryTreeLoadError,
  categoryNodes,
  corpora,
  disabled,
  graph,
  initialCategoryLineageId,
  isDemo,
  lexicalSteeringRules,
  references,
  semanticRelations,
  onArchiveDraftCategory,
  onCategorySave,
  onCreateAnalysisReindexAssignment,
  onCreateDraftCategory,
  onCreateDraftSet,
  onDiscardDraftSet,
  onLexicalRuleCreate,
  onPromoteDraftSet,
  onProposalAction,
  onReviewTopicLabel,
  onUpdateDraftCategory,
  proposals,
}: {
  activeCategoryTree: CategorySteeringCategoryTree | null;
  activeCategorySet: CategorySteeringCategorySet | null;
  analysisProfiles: AnalysisProfileSummary[];
  canonicalCategorys: CategorySteeringCategory[];
  categorySets: CategorySteeringCategorySet[];
  categorys: CategorySteeringCategory[];
  categoryByUid: Map<string, CategorySteeringCategory>;
  categoryKeywords: CategoryKeywordRecord[];
  categoryTreeLoadError: string | null;
  categoryNodes: CategorySteeringCategoryTreeNode[];
  corpora: CategorySteeringCorpus[];
  disabled: boolean;
  graph: SemanticGraph;
  initialCategoryLineageId?: string | null;
  isDemo?: boolean;
  lexicalSteeringRules: LexicalSteeringRuleRecord[];
  references: ReferenceRecord[];
  semanticRelations: SemanticRelationRecord[];
  onArchiveDraftCategory: (category: CategorySteeringCategory, note: string) => Promise<boolean> | boolean | void;
  onCategorySave: (category: CategorySteeringCategory, update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">) => void;
  onCreateAnalysisReindexAssignment: (profile: AnalysisProfileSummary, draft: AnalysisReindexDraft) => void;
  onCreateDraftCategory: (categorySet: CategorySteeringCategorySet, input: DraftCategoryInput) => Promise<boolean> | boolean | void;
  onCreateDraftSet: (sourceCategorySet: CategorySteeringCategorySet, displayName: string, note: string) => Promise<string | null> | string | null | void;
  onDiscardDraftSet: (categorySet: CategorySteeringCategorySet, note: string) => Promise<boolean> | boolean | void;
  onLexicalRuleCreate: (draft: LexicalRuleDraft) => void;
  onPromoteDraftSet: (categorySet: CategorySteeringCategorySet, note: string) => Promise<boolean> | boolean | void;
  onProposalAction: (proposal: CategorySteeringProposal, action: ReviewAction, input?: ProposalReviewInput) => void;
  onReviewTopicLabel: (input: { action: TopicLabelAction; category: CategorySteeringCategory; note?: string | null; reference: ReferenceRecord; sourceRelationId?: string | null }) => void;
  onUpdateDraftCategory: (category: CategorySteeringCategory, input: DraftCategoryInput) => Promise<boolean> | boolean | void;
  proposals: CategorySteeringProposal[];
}) {
  const currentCategorySet = activeCategorySet && isCurrentCategorySet(activeCategorySet) ? activeCategorySet : null;
  const activeDraftCategorySet = activeDraftForCurrentCategorySet(categorySets, categorys, currentCategorySet);
  const validCategorySets = [currentCategorySet, activeDraftCategorySet].filter(Boolean) as CategorySteeringCategorySet[];
  const defaultCategorySetId = currentCategorySet?.id ?? null;
  const [selectedCategorySetId, setSelectedCategorySetId] = useState<string | null>(activeCategorySet?.id ?? null);
  const [isCreatingTaxonomyDraft, setIsCreatingTaxonomyDraft] = useState(false);
  const [topicToolbarError, setTopicToolbarError] = useState<string | null>(null);
  const [topicDraftModal, setTopicDraftModal] = useState<TopicDraftModalState | null>(null);
  const [topicProposalEdit, setTopicProposalEdit] = useState<TopicProposalEditState | null>(null);
  const [isTopicToolbarMenuOpen, setIsTopicToolbarMenuOpen] = useState(false);
  const topicToolbarMenuRef = useRef<HTMLDivElement | null>(null);
  const selectedCategorySet = resolveTopicWorkspace(validCategorySets, selectedCategorySetId, defaultCategorySetId);
  const selectedCategorys = useMemo(() => {
    if (!selectedCategorySet) return [];
    return categorys.filter((category) => (
      category.categorySetId === selectedCategorySet.id
      && category.status !== "deprecated"
      && category.status !== "archived"
      && category.versionState !== "superseded"
    ));
  }, [categorys, selectedCategorySet]);
  const selectedCategoryNodes = useMemo(() => {
    if (selectedCategorySet?.id === activeCategoryTree?.id) return categoryNodes;
    return selectedCategorys.map(categoryToCategoryTreeNode);
  }, [activeCategoryTree?.id, categoryNodes, selectedCategorySet?.id, selectedCategorys]);
  const selectedCategoryByUid = useMemo(() => {
    const map = new Map<string, CategorySteeringCategory>();
    for (const category of selectedCategorys) map.set(category.categoryKey, category);
    return map;
  }, [selectedCategorys]);
  const referenceByAnyId = useMemo(() => buildReferenceLookupByAnyId(references), [references]);
  const categoryQueueProposals = useMemo(() => {
    const scoped = proposals.filter((proposal) => (
      proposal.steeringDomain === "category"
      && (!selectedCategorySet || proposal.categorySetId === selectedCategorySet.id)
    ));
    if (scoped.length > 0 || !selectedCategorySet) return scoped;
    return proposals.filter((proposal) => proposal.steeringDomain === "category");
  }, [proposals, selectedCategorySet]);
  const roots = buildCanonicalTopicRoots(selectedCategorys, selectedCategoryNodes, proposals);
  const subcategoryCount = roots.reduce((count, root) => count + root.subcategorys.length, 0);
  const proposedSubcategoryCount = roots.reduce((count, root) => count + root.proposedSubcategorys.length, 0);
  const isDraftMode = selectedCategorySet?.versionState === "draft" || selectedCategorySet?.status === "draft";
  const initialRootKey = selectInitialRootKey(roots, initialCategoryLineageId);
  const [selectedRootKey, setSelectedRootKey] = useState<string | null>(initialRootKey);
  const [focusedCategoryKey, setFocusedCategoryKey] = useState<string | null>(null);
  const [topicScopeFilter, setTopicScopeFilter] = useState("roots");
  const [topicMetricFilter, setTopicMetricFilter] = useState("");
  const [isTopicDetailOpen, setIsTopicDetailOpen] = useState(Boolean(initialCategoryLineageId));
  const selectedRoot = roots.find((root) => root.category.categoryKey === selectedRootKey) ?? roots[0] ?? null;
  const focusedNode = selectedRoot
    ? [categoryToCategoryTreeNode(selectedRoot.category), ...(selectedRoot.node ? [selectedRoot.node] : []), ...selectedRoot.subcategorys]
      .find((node) => node.categoryKey === focusedCategoryKey)
      ?? categoryToCategoryTreeNode(selectedRoot.category)
    : null;
  const topicKnowledgeQuery = useNewsroomKnowledgeContext(focusedNode ? {
    anchor: {
      kind: "category",
      id: focusedNode.id ?? focusedNode.categoryKey,
      lineageId: categoryLineageId(focusedNode),
    },
    title: focusedNode.displayName,
    subtitle: focusedNode.categoryKey,
  } : null);
  const focusedCategory = focusedNode
    ? selectedCategorys.find((category) => category.categoryKey === focusedNode.categoryKey) ?? categoryTreeNodeToCategory(focusedNode)
    : selectedRoot?.category ?? null;
  const editableCategory = focusedCategoryKey
    ? selectedCategoryByUid.get(focusedCategoryKey)
      ?? (selectedRoot?.category.categoryKey === focusedCategoryKey ? selectedRoot.category : undefined)
    : selectedRoot?.category;
  const proposalCountByCategoryKey = useMemo(() => {
    const counts = new Map<string, number>();
    for (const root of roots) {
      const rootNode = root.node ?? categoryToCategoryTreeNode(root.category);
      counts.set(
        rootNode.categoryKey,
        countRelatedCategoryTreeProposals(rootNode.categoryKey, root.subcategorys, proposals),
      );
      for (const subcategory of root.subcategorys) {
        counts.set(
          subcategory.categoryKey,
          countRelatedCategoryTreeProposals(subcategory.categoryKey, [], proposals),
        );
      }
    }
    return counts;
  }, [proposals, roots]);
  const rootWithProposalCount = useMemo(() => (
    roots.reduce((count, root) => (
      count + ((proposalCountByCategoryKey.get(root.category.categoryKey) ?? 0) > 0 ? 1 : 0)
    ), 0)
  ), [proposalCountByCategoryKey, roots]);
  const visibleRoots = topicMetricFilter === "withProposals"
    ? roots.filter((root) => (proposalCountByCategoryKey.get(root.category.categoryKey) ?? 0) > 0)
    : roots;
  const visibleTopicCards = useMemo(() => {
    const entries: Array<{
      kind: "root" | "subcategory";
      node: CategorySteeringCategoryTreeNode;
      parentCategoryKey: string | null;
      proposalCount: number;
      referenceCount: number;
      subtopicCount: number | null;
    }> = [];
    for (const root of visibleRoots) {
      const rootNode = root.node ?? categoryToCategoryTreeNode(root.category);
      const rootContext = buildTopicDrilldownContext(root, rootNode, categoryByUid);
      entries.push({
        kind: "root",
        node: rootNode,
        parentCategoryKey: null,
        proposalCount: proposalCountByCategoryKey.get(rootNode.categoryKey) ?? 0,
        referenceCount: referencesForCategoryContext(graph, rootContext).length,
        subtopicCount: root.subcategorys.length,
      });
      if (topicScopeFilter !== "all") continue;
      for (const subcategory of root.subcategorys) {
        const subcategoryContext = buildTopicDrilldownContext(root, subcategory, categoryByUid);
        entries.push({
          kind: "subcategory",
          node: subcategory,
          parentCategoryKey: rootNode.categoryKey,
          proposalCount: proposalCountByCategoryKey.get(subcategory.categoryKey) ?? 0,
          referenceCount: referencesForCategoryContext(graph, subcategoryContext).length,
          subtopicCount: null,
        });
      }
    }
    return entries.map((entry, index) => topicTreeNodeToNewsroomCard(entry, index));
  }, [categoryByUid, graph, proposalCountByCategoryKey, topicScopeFilter, visibleRoots]);
  const detail = activeCategoryTree || roots.length
    ? `${roots.length} canonical / ${subcategoryCount} accepted subtopics / ${proposedSubcategoryCount} proposed`
    : categoryTreeLoadError
      ? "CategoryTree unavailable"
      : validCategorySets.length ? "No active topics in selected set" : "No current or draft topic set available";
  const selectTopic = (categoryKey: string) => {
    const root = roots.find((candidate) => (
      candidate.category.categoryKey === categoryKey
      || candidate.subcategorys.some((subcategory) => subcategory.categoryKey === categoryKey)
    ));
    if (!root) return;
    const focused = root.category.categoryKey === categoryKey
      ? root.node ?? categoryToCategoryTreeNode(root.category)
      : root.subcategorys.find((subcategory) => subcategory.categoryKey === categoryKey) ?? root.node ?? categoryToCategoryTreeNode(root.category);
    setSelectedRootKey(root.category.categoryKey);
    setFocusedCategoryKey(focused.categoryKey);
    setIsTopicDetailOpen(true);
    pushNewsroomDetailUrl("topics", categoryLineageId(focused), isDemo);
  };
  const createEditableDraft = async () => {
    if (!currentCategorySet || isCreatingTaxonomyDraft) return;
    setTopicToolbarError(null);
    if (activeDraftCategorySet) {
      setSelectedCategorySetId(activeDraftCategorySet.id);
      return;
    }
    setIsCreatingTaxonomyDraft(true);
    try {
      const draftId = await Promise.resolve(onCreateDraftSet(
        currentCategorySet,
        buildEditableDraftName(currentCategorySet.displayName),
        "Created from the Topics dashboard for manual topic sculpting.",
      ));
      if (draftId) setSelectedCategorySetId(draftId);
    } catch (error) {
      setTopicToolbarError(error instanceof Error ? error.message : "Draft creation failed.");
    } finally {
      setIsCreatingTaxonomyDraft(false);
    }
  };
  const viewCurrentTaxonomy = () => {
    setSelectedCategorySetId(currentCategorySet?.id ?? null);
  };
  const topicActions: NewsroomDetailAction[] = isDraftMode && selectedCategorySet && editableCategory ? [
    {
      key: "edit-topic",
      label: "Edit Topic",
      disabled,
      onSelect: () => setTopicDraftModal({ kind: "edit", category: editableCategory }),
    },
    {
      key: "add-child-topic",
      label: "Add Child Topic",
      disabled,
      onSelect: () => setTopicDraftModal({ kind: "create", parentCategoryKey: editableCategory.categoryKey }),
    },
    {
      key: "archive-topic",
      label: "Deprecate Topic",
      disabled,
      onSelect: () => setTopicDraftModal({ kind: "archive", category: editableCategory }),
    },
  ] : [];
  const topicToolbarActions: NewsroomDetailAction[] = isDraftMode && selectedCategorySet
    ? [
      {
        key: "add-topic",
        label: "Add Topic",
        disabled,
        onSelect: () => setTopicDraftModal({ kind: "create", parentCategoryKey: null }),
      },
      {
        key: "promote-draft",
        label: "Promote Draft",
        disabled,
        onSelect: () => setTopicDraftModal({ kind: "promote" }),
      },
      {
        key: "discard-draft",
        label: "Discard Draft",
        disabled,
        onSelect: () => setTopicDraftModal({ kind: "discard" }),
      },
      {
        key: "view-current",
        label: "View Current",
        disabled: disabled || !currentCategorySet,
        onSelect: viewCurrentTaxonomy,
      },
    ]
    : currentCategorySet
      ? [
        {
          key: "edit-taxonomy",
          label: isCreatingTaxonomyDraft ? "Creating Draft" : topicToolbarError ? "Draft Failed" : "Edit Taxonomy",
          disabled: disabled || isCreatingTaxonomyDraft,
          onSelect: createEditableDraft,
        },
      ]
      : [];
  const topicLedeControls = topicToolbarActions.length || isDraftMode ? (
    <div className="news-desk-topic-lede-controls">
      {topicToolbarActions.length ? (
        <div className="newsroom-list-detail-shell__action-menu-wrap news-desk-topic-list-toolbar" ref={topicToolbarMenuRef}>
          <button
            type="button"
            aria-label="Taxonomy actions"
            aria-expanded={isTopicToolbarMenuOpen}
            className="news-desk-detail-toggle news-desk-detail-toggle--actions"
            title={topicToolbarError ?? undefined}
            disabled={topicToolbarActions.every((action) => action.disabled)}
            onClick={() => setIsTopicToolbarMenuOpen((current) => !current)}
          >
            <EllipsisIcon />
          </button>
          {isTopicToolbarMenuOpen ? (
            <div className="newsroom-list-detail-shell__action-menu news-desk-topic-toolbar-menu" role="menu">
              {topicToolbarActions.map((action) => (
                <button
                  type="button"
                  disabled={action.disabled}
                  key={action.key}
                  onClick={() => {
                    setIsTopicToolbarMenuOpen(false);
                    action.onSelect();
                  }}
                  role="menuitem"
                >
                  {action.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {isDraftMode ? (
        <div className="news-desk-assignment-create-strip">
          <span className="news-desk-assignment-create-note">Draft taxonomy</span>
          <span className="news-desk-assignment-create-note">
            Draft edits do not affect publication sections until promoted.
          </span>
        </div>
      ) : null}
    </div>
  ) : null;
  const selectedTopicCardId = focusedCategoryKey ?? selectedRoot?.category.categoryKey ?? null;

  useEffect(() => {
    if (!roots.length) {
      setSelectedRootKey(null);
      setFocusedCategoryKey(null);
      return;
    }
    const nextRootKey = roots.some((root) => root.category.categoryKey === selectedRootKey)
      ? selectedRootKey
      : initialRootKey ?? roots[0].category.categoryKey;
    if (selectedRootKey !== nextRootKey) setSelectedRootKey(nextRootKey);
  }, [initialRootKey, roots, selectedRootKey]);

  useEffect(() => {
    if (!selectedRoot) return;
    const nextFocusKey = selectInitialFocusKey(selectedRoot, initialCategoryLineageId);
    if (!focusedCategoryKey || ![selectedRoot.category.categoryKey, ...selectedRoot.subcategorys.map((subcategory) => subcategory.categoryKey)].includes(focusedCategoryKey)) {
      setFocusedCategoryKey(nextFocusKey);
    }
  }, [focusedCategoryKey, initialCategoryLineageId, selectedRoot]);

  useEffect(() => {
    const normalizedCategorySetId = selectedCategorySet?.id ?? null;
    if (selectedCategorySetId === normalizedCategorySetId) return;
    setSelectedCategorySetId(normalizedCategorySetId);
  }, [selectedCategorySet?.id, selectedCategorySetId]);

  useEffect(() => {
    if (!isTopicToolbarMenuOpen) return;
    function handlePointerDown(event: PointerEvent) {
      if (topicToolbarMenuRef.current?.contains(event.target as Node)) return;
      setIsTopicToolbarMenuOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsTopicToolbarMenuOpen(false);
    }
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isTopicToolbarMenuOpen]);

  return (
    <>
    <NewsroomListDetailShell
      animatedDetail
      sectionKey="topics"
      canExpandDetail={Boolean(selectedRoot)}
      detailOpen={isTopicDetailOpen}
      selectionScrollKey={selectedTopicCardId}
      actions={topicActions}
      utilityActions={[topicKnowledgeQuery.action]}
      lede={(
        <NewsroomDeskSectionLede
          headingId="topic-management-title"
          section="topics"
          controls={topicLedeControls}
        />
      )}
      list={(
        <section className="category-steering-section category-steering-section--lead" aria-label={detail}>
          {categoryTreeLoadError ? (
            <div className="category-steering-alert" role="status">
              {categoryTreeLoadError}
            </div>
          ) : null}
          <TopicProposalQueue
            disabled={disabled}
            proposals={categoryQueueProposals}
            referenceByAnyId={referenceByAnyId}
            onAction={onProposalAction}
            onEdit={(proposal) => setTopicProposalEdit({ proposal })}
            onFocusTopic={selectTopic}
          />
          <NewsroomCardGrid
            cards={visibleTopicCards}
            emptyLabel={categoryTreeLoadError ?? (validCategorySets.length ? "No active topics in selected topic set" : "No current or draft topic set available.")}
            filterLabel="Topic scope"
            filterOptions={[
              { key: "roots", label: isDraftMode ? "Top-level draft topics" : "Top-level current topics", count: roots.length },
              { key: "all", label: isDraftMode ? "Draft topics + subtopics" : "Current topics + subtopics", count: roots.length + subcategoryCount },
            ]}
            filterValue={topicScopeFilter}
            metricValue={topicMetricFilter}
            metrics={[
              { key: "", label: "All", count: visibleTopicCards.length },
              { key: "withProposals", label: "With proposals", count: rootWithProposalCount },
            ]}
            onFilterChange={setTopicScopeFilter}
            onMetricChange={setTopicMetricFilter}
            onSelect={selectTopic}
            selectedId={selectedTopicCardId}
          />
        </section>
      )}
      onCloseDetail={() => setIsTopicDetailOpen(false)}
      detail={selectedRoot ? (
        <section className="category-steering-section" aria-label="Topic detail">
          <CanonicalTopicDetail
            categoryByUid={selectedCategoryByUid}
            disabled={disabled}
            focusedCategoryKey={focusedCategoryKey}
            focusedNode={focusedNode}
            graph={graph}
            categoryKeywords={categoryKeywords}
            lexicalSteeringRules={lexicalSteeringRules}
            onAction={onProposalAction}
            onEdit={(proposal) => setTopicProposalEdit({ proposal })}
            onFocusCategory={setFocusedCategoryKey}
            onLexicalRuleCreate={onLexicalRuleCreate}
            proposals={proposals}
            referenceByAnyId={referenceByAnyId}
            root={selectedRoot}
            knowledgeQuery={topicKnowledgeQuery}
          />
        </section>
      ) : (
        <section className="category-steering-section">
          <EmptyRow label="Select a canonical topic to inspect subtopics and context." />
        </section>
      )}
    />
    {topicKnowledgeQuery.dialog}
    {topicProposalEdit ? (
      <TopicProposalEditModal
        disabled={disabled}
        proposal={topicProposalEdit.proposal}
        onClose={() => setTopicProposalEdit(null)}
        onSave={(proposal, input) => {
          onProposalAction(proposal, "edit", input);
          setTopicProposalEdit(null);
        }}
      />
    ) : null}
    {topicDraftModal && selectedCategorySet ? (
      <TopicDraftActionModal
        categorySet={selectedCategorySet}
        disabled={disabled}
        modal={topicDraftModal}
        onArchive={async (category, note) => {
          const result = await onArchiveDraftCategory(category, note);
          setSelectedCategorySetId(selectedCategorySet.id);
          return result ?? true;
        }}
        onClose={() => setTopicDraftModal(null)}
        onCreate={async (categorySet, input) => {
          const result = await onCreateDraftCategory(categorySet, input);
          setSelectedCategorySetId(categorySet.id);
          return result ?? true;
        }}
        onDiscard={async (categorySet, note) => {
          const result = await onDiscardDraftSet(categorySet, note);
          setSelectedCategorySetId(currentCategorySet?.id ?? null);
          return result ?? true;
        }}
        onPromote={onPromoteDraftSet}
        onUpdate={async (category, input) => {
          const result = await onUpdateDraftCategory(category, input);
          setSelectedCategorySetId(selectedCategorySet.id);
          return result ?? true;
        }}
        parentOptions={selectedCategorys}
      />
    ) : null}
    </>
  );
}

function TopicDraftActionModal({
  categorySet,
  disabled,
  modal,
  onArchive,
  onClose,
  onCreate,
  onDiscard,
  onPromote,
  onUpdate,
  parentOptions,
}: {
  categorySet: CategorySteeringCategorySet;
  disabled: boolean;
  modal: TopicDraftModalState;
  onArchive: (category: CategorySteeringCategory, note: string) => Promise<boolean> | boolean | void;
  onClose: () => void;
  onCreate: (categorySet: CategorySteeringCategorySet, input: DraftCategoryInput) => Promise<boolean> | boolean | void;
  onDiscard: (categorySet: CategorySteeringCategorySet, note: string) => Promise<boolean> | boolean | void;
  onPromote: (categorySet: CategorySteeringCategorySet, note: string) => Promise<boolean> | boolean | void;
  onUpdate: (category: CategorySteeringCategory, input: DraftCategoryInput) => Promise<boolean> | boolean | void;
  parentOptions: CategorySteeringCategory[];
}) {
  const editingCategory = modal.kind === "edit" || modal.kind === "archive" ? modal.category : null;
  const isCreate = modal.kind === "create";
  const isEdit = modal.kind === "edit";
  const isArchive = modal.kind === "archive";
  const isPromote = modal.kind === "promote";
  const isDiscard = modal.kind === "discard";
  const [displayName, setDisplayName] = useState(isEdit ? editingCategory?.displayName ?? "" : "");
  const [shortTitle, setShortTitle] = useState(isEdit ? editingCategory?.shortTitle ?? deriveShortTitle(editingCategory?.displayName) : "");
  const [subtitle, setSubtitle] = useState(isEdit ? editingCategory?.subtitle ?? "" : "");
  const [description, setDescription] = useState(isEdit ? editingCategory?.description ?? "" : "");
  const [parentCategoryKey, setParentCategoryKey] = useState(isEdit ? editingCategory?.parentCategoryKey ?? "" : isCreate ? modal.parentCategoryKey ?? "" : "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const category = modal.kind === "edit" || modal.kind === "archive" ? modal.category : null;
    setDisplayName(modal.kind === "edit" ? category?.displayName ?? "" : "");
    setShortTitle(modal.kind === "edit" ? category?.shortTitle ?? deriveShortTitle(category?.displayName) : "");
    setSubtitle(modal.kind === "edit" ? category?.subtitle ?? "" : "");
    setDescription(modal.kind === "edit" ? category?.description ?? "" : "");
    setParentCategoryKey(modal.kind === "edit" ? category?.parentCategoryKey ?? "" : modal.kind === "create" ? modal.parentCategoryKey ?? "" : "");
    setNote("");
    setError(null);
    setIsSubmitting(false);
  }, [modal]);

  const title = isCreate ? (parentCategoryKey ? "Add Child Topic" : "Add Topic") : isEdit ? "Edit Topic" : isArchive ? "Deprecate Topic" : isDiscard ? "Discard Draft" : "Promote Draft";
  const detail = isPromote
    ? "Make this draft the current publication-facing taxonomy."
    : isDiscard
      ? "Hard-delete this draft workspace and return to the current taxonomy."
    : isArchive
      ? "Deprecate this topic inside the draft taxonomy."
      : "Draft edits do not affect publication sections until promoted.";
  const valid = isArchive || isDiscard ? Boolean(note.trim()) : isPromote ? true : Boolean(displayName.trim());

  async function handleSubmit() {
    if (!valid || isSubmitting) return;
    setError(null);
    setIsSubmitting(true);
    try {
      if (isCreate) {
        const result = await onCreate(categorySet, {
          displayName: displayName.trim(),
          shortTitle: shortTitle.trim() || deriveShortTitle(displayName),
          subtitle: subtitle.trim() || null,
          description: description.trim() || null,
          parentCategoryKey: parentCategoryKey || null,
          note: note.trim() || null,
        });
        if (result === false) throw new Error("Topic creation failed.");
      } else if (isEdit && editingCategory) {
        const result = await onUpdate(editingCategory, {
          displayName: displayName.trim(),
          shortTitle: shortTitle.trim() || deriveShortTitle(displayName),
          subtitle: subtitle.trim() || null,
          description: description.trim() || null,
          parentCategoryKey: parentCategoryKey || null,
          note: note.trim() || null,
        });
        if (result === false) throw new Error("Topic update failed.");
      } else if (isArchive && editingCategory) {
        const result = await onArchive(editingCategory, note.trim());
        if (result === false) throw new Error("Topic archive failed.");
      } else if (isPromote) {
        const result = await onPromote(categorySet, note.trim());
        if (result === false) throw new Error("Draft promotion failed.");
      } else if (isDiscard) {
        const result = await onDiscard(categorySet, note.trim());
        if (result === false) throw new Error("Draft discard failed.");
      }
      onClose();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Topic draft action failed.");
      setIsSubmitting(false);
    }
  }

  return (
    <div
      className="news-desk-modal"
      data-news-desk-topic-draft-modal
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isSubmitting) onClose();
      }}
    >
      <div className="news-desk-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="topic-draft-action-title">
        <header className="news-desk-modal__header">
          <div>
            <p className="story-label">Taxonomy Draft</p>
            <h3 id="topic-draft-action-title">{title}</h3>
            <span>{detail}</span>
          </div>
          <button type="button" disabled={isSubmitting} onClick={onClose}>Close</button>
        </header>
        {isArchive || isPromote || isDiscard ? (
          <div className="news-desk-topic-draft-confirm">
            <p className="news-desk-detail-copy">
              {isDiscard
                ? `This will delete "${categorySet.displayName}" and all draft topic edits. The current taxonomy is unchanged.`
                : isArchive && editingCategory
                  ? `This will deprecate "${editingCategory.displayName}" inside the draft. The current taxonomy is unchanged.`
                  : `This will promote "${categorySet.displayName}" and supersede the previous current taxonomy.`}
            </p>
            <label>
              <span>{isArchive || isDiscard ? "Required note" : "Promotion note"}</span>
              <textarea
                disabled={disabled || isSubmitting}
                onChange={(event) => setNote(event.target.value)}
                placeholder={isDiscard ? "Why should this draft be discarded?" : isArchive ? "Why should this topic be deprecated?" : "Why is this draft ready for publication?"}
                rows={3}
                value={note}
              />
            </label>
          </div>
        ) : (
          <div className="news-desk-topic-draft-form">
            <label>
              <span>Name</span>
              <input disabled={disabled || isSubmitting} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
            <label>
              <span>Short title</span>
              <input disabled={disabled || isSubmitting} value={shortTitle} onChange={(event) => setShortTitle(event.target.value)} placeholder={deriveShortTitle(displayName)} />
            </label>
            <label>
              <span>Subtitle</span>
              <input disabled={disabled || isSubmitting} value={subtitle} onChange={(event) => setSubtitle(event.target.value)} />
            </label>
            <label>
              <span>Description</span>
              <textarea disabled={disabled || isSubmitting} rows={4} value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label>
              <span>Parent topic</span>
              <select disabled={disabled || isSubmitting} value={parentCategoryKey} onChange={(event) => setParentCategoryKey(event.target.value)}>
                <option value="">Top-level topic</option>
                {parentOptions.filter((entry) => entry.categoryKey !== editingCategory?.categoryKey).map((entry) => (
                  <option key={entry.id} value={entry.categoryKey}>{entry.displayName}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Change note</span>
              <input disabled={disabled || isSubmitting} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why this taxonomy edit?" />
            </label>
          </div>
        )}
        {error ? <div className="category-steering-alert" role="status">{error}</div> : null}
        <footer className="news-desk-modal__actions">
          <button type="button" disabled={isSubmitting} onClick={onClose}>Cancel</button>
          <button type="button" className="news-desk-assignment-create-button" disabled={disabled || isSubmitting || !valid} onClick={handleSubmit}>
            {isSubmitting ? "Saving" : isDiscard ? "Discard Draft" : isArchive ? "Deprecate Topic" : isPromote ? "Promote Draft" : isCreate ? "Create Topic" : "Save Topic"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function TopicProposalEditModal({
  disabled,
  proposal,
  onClose,
  onSave,
}: {
  disabled: boolean;
  proposal: CategorySteeringProposal;
  onClose: () => void;
  onSave: (proposal: CategorySteeringProposal, input: ProposalReviewInput) => void;
}) {
  const [displayName, setDisplayName] = useState(proposal.displayName ?? proposal.title ?? "");
  const [shortTitle, setShortTitle] = useState(proposal.shortTitle ?? deriveShortTitle(proposal.displayName ?? proposal.title));
  const [subtitle, setSubtitle] = useState(proposal.subtitle ?? "");
  const [description, setDescription] = useState(proposal.description ?? proposal.summary ?? "");
  const [aliases, setAliases] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    setDisplayName(proposal.displayName ?? proposal.title ?? "");
    setShortTitle(proposal.shortTitle ?? deriveShortTitle(proposal.displayName ?? proposal.title));
    setSubtitle(proposal.subtitle ?? "");
    setDescription(proposal.description ?? proposal.summary ?? "");
    setAliases("");
    setNote("");
  }, [proposal]);

  const canSave = Boolean(displayName.trim());
  return (
    <div
      className="news-desk-modal"
      data-news-desk-topic-proposal-edit-modal
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="news-desk-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="topic-proposal-edit-title">
        <header className="news-desk-modal__header">
          <div>
            <p className="story-label">Topic Proposal Edit</p>
            <h3 id="topic-proposal-edit-title">{proposal.title}</h3>
            <span>Manually correct LLM labels, then accept this proposal.</span>
          </div>
          <button type="button" onClick={onClose}>Close</button>
        </header>
        <div className="news-desk-topic-draft-form">
          <label>
            <span>Name</span>
            <input disabled={disabled} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </label>
          <label>
            <span>Short title</span>
            <input disabled={disabled} value={shortTitle} onChange={(event) => setShortTitle(event.target.value)} />
          </label>
          <label>
            <span>Subtitle</span>
            <input disabled={disabled} value={subtitle} onChange={(event) => setSubtitle(event.target.value)} />
          </label>
          <label>
            <span>Description</span>
            <textarea disabled={disabled} rows={4} value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <label>
            <span>Aliases (comma-separated)</span>
            <input disabled={disabled} value={aliases} onChange={(event) => setAliases(event.target.value)} placeholder="Optional aliases" />
          </label>
          <label>
            <span>Review note</span>
            <input disabled={disabled} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional note" />
          </label>
        </div>
        <footer className="news-desk-modal__actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="news-desk-assignment-create-button"
            data-review-action="edit-save-accept"
            disabled={disabled || !canSave}
            onClick={() => onSave(proposal, {
              displayName: displayName.trim(),
              shortTitle: shortTitle.trim() || deriveShortTitle(displayName),
              subtitle: subtitle.trim() || null,
              description: description.trim() || null,
              aliases: aliases
                .split(",")
                .map((entry) => entry.trim())
                .filter(Boolean),
              note: note.trim() || null,
              seedItemIds: compactArray(proposal.suggestedSeedItemIds),
              holdoutItemIds: compactArray(proposal.suggestedHoldoutItemIds),
            })}
          >
            Save &amp; Accept
          </button>
        </footer>
      </div>
    </div>
  );
}

function ConceptsDeskView({
  categories,
  disabled,
  graph,
  initialCategoryLineageId,
  initialNodeLineageId,
  onCreateInsight,
  semanticNodes,
  summary,
}: {
  categories: CategorySteeringCategory[];
  disabled: boolean;
  graph: SemanticGraph;
  initialCategoryLineageId?: string | null;
  initialNodeLineageId?: string | null;
  onCreateInsight: (target: InsightTarget, summary: string, body: string) => Promise<void>;
  semanticNodes: SemanticNodeRecord[];
  summary?: NewsroomSummaryRecord | null;
}) {
  const [nodeKindFilter, setNodeKindFilter] = useState("");
  const [nodeStatusFilter, setNodeStatusFilter] = useState("");
  const [selectedNodeLineageId, setSelectedNodeLineageId] = useState(initialNodeLineageId ?? "");
  const [isConceptDetailOpen, setIsConceptDetailOpen] = useState(Boolean(initialNodeLineageId));
  const categoryContext = useMemo(() => buildCategoryDrilldownContext(categories, initialCategoryLineageId), [categories, initialCategoryLineageId]);
  const feed = useNewsroomPagedRows({
    initialItems: semanticNodes,
    enabled: !categoryContext?.primary,
    resetKey: `semanticNodes:${nodeKindFilter}:${nodeStatusFilter}`,
    loadPage: (nextToken) => loadNewsroomSemanticNodePage({
      nodeKind: nodeKindFilter,
      status: nodeStatusFilter,
      nextToken,
    }),
  });
  const categoryFilter = categoryContext.primary ? graph.resolve("category", categoryLineageId(categoryContext.primary)) : null;
  const categoryConceptLineages = useMemo(() => (
    categoryContext.primary
      ? new Set(semanticNodesForCategoryContext(graph, categoryContext).map((node) => node.lineageId))
      : null
  ), [categoryContext, graph]);
  const feedNodes = useMemo(() => (
    feed.items.length
      ? feed.items
      : (feed.isLoading || Boolean(feed.error))
        ? semanticNodes
        : feed.items
  ), [feed.error, feed.isLoading, feed.items, semanticNodes]);
  const visibleNodes = useMemo(() => (
    categoryConceptLineages
      ? semanticNodes.filter((node) => categoryConceptLineages.has(node.lineageId ?? node.id))
      : feedNodes
  ), [categoryConceptLineages, feedNodes, semanticNodes]);
  const fallbackConceptCategories = useMemo(() => (
    visibleNodes.length
      ? []
      : categories.filter((category) => category.status !== "deprecated" && category.status !== "archived")
  ), [categories, visibleNodes.length]);
  const requestedNodeLineageId = selectedNodeLineageId || initialNodeLineageId || "";
  const selected = selectSemanticNodeSummary(graph, visibleNodes, requestedNodeLineageId)
    ?? (requestedNodeLineageId ? selectSemanticNodeSummary(graph, semanticNodes, requestedNodeLineageId) : null)
    ?? (requestedNodeLineageId ? selectCategorySummary(graph, categories, requestedNodeLineageId) : null)
    ?? categoryFilter
    ?? selectSemanticNodeSummary(graph, visibleNodes)
    ?? selectCategorySummary(graph, fallbackConceptCategories);
  const conceptKnowledgeQuery = useNewsroomKnowledgeContext(selected ? {
    anchor: {
      kind: selected.kind === "category" ? "category" : "semanticNode",
      id: selected.id ?? selected.lineageId,
      lineageId: selected.lineageId,
    },
    title: selected.label,
    subtitle: selected.subtitle,
  } : null);
  const conceptInsight = useNewsroomInsightComposer(
    selected && (selected.kind === "category" || selected.kind === "semanticNode") ? insightTargetForSemanticObject(selected) : null,
    disabled,
    onCreateInsight,
  );
  const detail = categoryFilter
    ? `${visibleNodes.length} graph nodes associated with ${categoryFilter.label}`
    : visibleNodes.length
      ? `${summaryCountFromRecord(summary, "semanticNodes") || visibleNodes.length} graph nodes`
      : `${fallbackConceptCategories.length} taxonomy concepts`;
  const nodeKindCounts = categoryFilter ? countSemanticNodesByKind(visibleNodes) : summary?.facets?.semanticNodes?.byNodeKind ?? countSemanticNodesByKind(visibleNodes);
  const nodeStatusCounts = categoryFilter ? countSemanticNodesByStatus(visibleNodes) : summary?.facets?.semanticNodes?.byStatus ?? countSemanticNodesByStatus(visibleNodes);
  const nodeKinds = sortedCountOptions(nodeKindCounts).slice(0, 8);
  const cards = visibleNodes.length
    ? visibleNodes.map((node, index) => semanticNodeToNewsroomCard(node, index))
    : fallbackConceptCategories.map((category, index) => categoryToConceptNewsroomCard(category, index));
  const cardIds = useMemo(() => new Set(cards.map((card) => card.id)), [cards]);
  const selectedLineageId = selected && cardIds.has(selected.lineageId) ? selected.lineageId : null;
  const selectNode = (lineageId: string) => {
    setSelectedNodeLineageId(lineageId);
    setIsConceptDetailOpen(true);
    pushNewsroomDetailUrl("concepts", lineageId, false);
  };
  return (
    <>
      <NewsroomListDetailShell
        animatedDetail
        sectionKey="concepts"
        canExpandDetail={Boolean(selected)}
        detailOpen={isConceptDetailOpen}
        selectionScrollKey={selectedLineageId}
        actions={[conceptInsight.action]}
        utilityActions={[conceptKnowledgeQuery.action]}
        lede={(
          <NewsroomDeskSectionLede headingId="semantic-concepts-title" section="concepts" />
        )}
        list={(
          <section className="category-steering-section category-steering-section--lead" aria-label={detail}>
            <NewsroomCardGrid
              cards={cards}
              emptyLabel={feed.isLoading ? "Loading semantic concepts" : feed.error ?? "No semantic nodes imported"}
              filterLabel="Concept kind"
              filterOptions={[
                { key: "", label: "All concept kinds", count: summaryCountFromRecord(summary, "semanticNodes") || visibleNodes.length },
                ...nodeKinds.map((option) => ({ key: option.key, label: formatAssignmentTypeLabel(option.key), count: option.count })),
              ]}
              filterValue={nodeKindFilter}
              footerLabel={feed.error ?? undefined}
              hasMore={!categoryFilter && feed.hasMore}
              isLoadingMore={feed.isLoadingMore}
              metricValue={nodeStatusFilter}
              metrics={[
                { key: "", label: "All", count: summaryCountFromRecord(summary, "semanticNodes") || visibleNodes.length },
                ...sortedCountOptions(nodeStatusCounts).map((option) => ({ key: option.key, label: option.key, count: option.count })),
              ]}
              onFilterChange={setNodeKindFilter}
              onLoadMore={feed.loadMore}
              onMetricChange={setNodeStatusFilter}
              onSelect={selectNode}
              selectedId={selectedLineageId}
            />
          </section>
        )}
        onCloseDetail={() => setIsConceptDetailOpen(false)}
        detail={<SemanticDetailPanel graph={graph} selected={selected} knowledgeQuery={conceptKnowledgeQuery} />}
      />
      {conceptKnowledgeQuery.dialog}
      {conceptInsight.dialog}
    </>
  );
}

function ReferencesDeskView({
  categories,
  categorySets,
  corpora,
  curationRunsByLineage,
  disabled,
  graph,
  initialCategoryLineageId,
  initialReferenceLineageId,
  isDemo,
  deepLinkFetchEnabled = true,
  onCreateInsight,
  onHydrateReference,
  onMoveCorpus,
  onReview,
  onStartCuration,
  onSetQualityRating,
  onReviewTopicLabel,
  qualityActionState,
  realtimeError,
  realtimeStatus,
  references,
  referenceAttachments,
  semanticRelations,
  summary,
}: {
  categories: CategorySteeringCategory[];
  categorySets: CategorySteeringCategorySet[];
  corpora: CategorySteeringCorpus[];
  curationRunsByLineage: Record<string, ReferenceCurationRunStatus>;
  disabled: boolean;
  graph: SemanticGraph;
  initialCategoryLineageId?: string | null;
  initialReferenceLineageId?: string | null;
  isDemo?: boolean;
  deepLinkFetchEnabled?: boolean;
  onCreateInsight: (target: InsightTarget, summary: string, body: string) => Promise<void>;
  onHydrateReference?: (reference: ReferenceRecord) => void;
  onMoveCorpus: (reference: ReferenceRecord, corpusId: string) => void;
  onReview: (reference: ReferenceRecord, action: ReferenceCurationAction, note?: string, reasonCode?: ReferenceRejectionReasonCode | null) => void;
  onStartCuration: (reference: ReferenceRecord) => void;
  onSetQualityRating: (reference: ReferenceRecord, rating: number) => void;
  onReviewTopicLabel: (input: { action: TopicLabelAction; category: CategorySteeringCategory; note?: string | null; reference: ReferenceRecord; sourceRelationId?: string | null }) => void;
  qualityActionState: ReferenceQualityActionState | null;
  realtimeError?: string | null;
  realtimeStatus?: RealtimeSubscriptionStatus;
  references: ReferenceRecord[];
  referenceAttachments: ReferenceAttachmentRecord[];
  semanticRelations: SemanticRelationRecord[];
  summary?: NewsroomSummaryRecord | null;
}) {
  const pathname = usePathname();
  const pathnameReferenceLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeReferenceLineageId = initialReferenceLineageId ?? pathnameReferenceLineageId ?? "";
  const consoleContext = usePapyrusConsole();
  const [statusFilter, setStatusFilter] = useState(() => {
    if (typeof window === "undefined") return "__exclude_pending";
    return referencesStatusFromUrl(readReferencesIndexFilters(new URLSearchParams(window.location.search)).status);
  });
  const [processingFilter, setProcessingFilter] = useState(() => {
    if (typeof window === "undefined") return "";
    return readReferencesIndexFilters(new URLSearchParams(window.location.search)).processing;
  });
  const [orderFilter, setOrderFilter] = useState<ReferenceIndexOrder>(() => {
    if (typeof window === "undefined") return "published";
    return readReferencesIndexFilters(new URLSearchParams(window.location.search)).order;
  });
  const [selectedReferenceLineageId, setSelectedReferenceLineageId] = useState(routeReferenceLineageId);
  const [isReferenceDetailOpen, setIsReferenceDetailOpen] = useState(Boolean(routeReferenceLineageId));
  const [deepLinkReferenceLoading, setDeepLinkReferenceLoading] = useState(false);
  const [deepLinkReferenceError, setDeepLinkReferenceError] = useState<string | null>(null);
  const categoryContext = useMemo(() => buildCategoryDrilldownContext(categories, initialCategoryLineageId), [categories, initialCategoryLineageId]);
  const statusFilterValue = statusFilter === "__exclude_pending" ? "" : statusFilter;
  const syncReferencesIndexUrl = useCallback((
    nextStatus: string,
    nextProcessing: string,
    nextOrder: ReferenceIndexOrder,
    replace = true,
  ) => {
    if (categoryContext.primary || isDemo) return;
    if (parseReferenceLineageIdFromNewsroomPathname(typeof window !== "undefined" ? window.location.pathname : null)) {
      return;
    }
    syncBrowserNewsroomIndexUrl(
      "references",
      effectiveReferencesIndexFilters({
        status: referencesStatusToUrl(nextStatus),
        processing: nextProcessing,
        order: nextOrder,
      }),
      { replace },
    );
  }, [categoryContext.primary, isDemo]);
  useEffect(() => {
    if (!pathnameReferenceLineageId || isDemo) return;
    setSelectedReferenceLineageId((current) => current || pathnameReferenceLineageId);
    setIsReferenceDetailOpen(true);
  }, [isDemo, pathnameReferenceLineageId]);

  useEffect(() => {
    if (categoryContext.primary || isDemo || isReferenceDetailOpen || pathnameReferenceLineageId) return;
    syncReferencesIndexUrl(statusFilter, processingFilter, orderFilter, true);
  }, [categoryContext.primary, isDemo, isReferenceDetailOpen, orderFilter, pathnameReferenceLineageId, processingFilter, statusFilter, syncReferencesIndexUrl]);
  const feed = useNewsroomPagedRows({
    initialItems: references,
    enabled: !isDemo && !categoryContext.primary,
    resetKey: `references:${statusFilter}:${processingFilter}:${orderFilter}`,
    loadPage: (nextToken) => loadNewsroomReferencePage({
      status: statusFilterValue,
      excludePending: statusFilter === "__exclude_pending",
      order: orderFilter,
      nextToken,
    }),
  });
  const categoryFilter = categoryContext.primary ? graph.resolve("category", categoryLineageId(categoryContext.primary)) : null;
  const categoryReferenceLineages = useMemo(() => (
    categoryContext.primary
      ? new Set(referencesForCategoryContext(graph, categoryContext).map((reference) => reference.lineageId))
      : null
  ), [categoryContext, graph]);
  const visibleReferences = useMemo(() => (
    categoryReferenceLineages
      ? references.filter((reference) => categoryReferenceLineages.has(reference.lineageId ?? reference.id))
      : isDemo ? references : feed.items
  ), [categoryReferenceLineages, feed.items, isDemo, references]);
  const canonicalVisibleReferences = useMemo(
    () => selectCanonicalReferenceRecords(visibleReferences),
    [visibleReferences],
  );
  const statusFilteredReferences = canonicalVisibleReferences
    .filter((reference) => {
      const effectiveStatus = normalizeReferenceStatus(reference.curationStatus);
      if (statusFilter === "__exclude_pending") return effectiveStatus !== "pending";
      if (!statusFilter) return true;
      return effectiveStatus === statusFilter;
    });
  const filteredReferences = statusFilteredReferences
    .filter((reference) => {
      if (!processingFilter) return true;
      const processed = isReferenceProcessed(reference, referenceAttachments);
      return processingFilter === "processed" ? processed : !processed;
    });
  const requestedReferenceLineageId = selectedReferenceLineageId || routeReferenceLineageId;
  const selectedReference = requestedReferenceLineageId
    ? selectedReferenceRecordByLineage(filteredReferences, requestedReferenceLineageId)
      ?? selectedReferenceRecordByLineage(canonicalVisibleReferences, requestedReferenceLineageId)
      ?? selectedReferenceRecordByLineage(references, requestedReferenceLineageId)
      ?? null
    : null;

  useEffect(() => {
    if (!requestedReferenceLineageId || isDemo || !deepLinkFetchEnabled || selectedReference) {
      setDeepLinkReferenceLoading(false);
      setDeepLinkReferenceError(null);
      return;
    }
    let active = true;
    setDeepLinkReferenceLoading(true);
    setDeepLinkReferenceError(null);
    void loadReferenceRecordByLineageId(requestedReferenceLineageId)
      .then((reference) => {
        if (!active) return;
        if (!reference) {
          setDeepLinkReferenceError(`Reference not found: ${requestedReferenceLineageId}`);
          setDeepLinkReferenceLoading(false);
          return;
        }
        onHydrateReference?.(reference);
        setSelectedReferenceLineageId(reference.lineageId ?? reference.id);
        setIsReferenceDetailOpen(true);
        setDeepLinkReferenceLoading(false);
      })
      .catch((error) => {
        if (!active) return;
        setDeepLinkReferenceError(error instanceof Error ? error.message : "Could not load reference.");
        setDeepLinkReferenceLoading(false);
      });
    return () => {
      active = false;
    };
  }, [deepLinkFetchEnabled, isDemo, onHydrateReference, requestedReferenceLineageId, selectedReference]);

  const referenceKnowledgeQuery = useNewsroomKnowledgeContext(selectedReference ? {
    anchor: { kind: "reference", id: selectedReference.id, lineageId: selectedReference.lineageId ?? selectedReference.id },
    title: selectedReference.title ?? selectedReference.externalItemId,
    subtitle: selectedReference.corpusId,
  } : null);
  const referenceChatAction: NewsroomDetailAction | null = selectedReference && consoleContext?.shouldOfferConsole ? {
    ariaLabel: "Open chat with this reference",
    disabled: disabled || consoleContext.openingReferenceChat,
    icon: <PapyrusConsoleChatIcon />,
    key: "reference-chat",
    label: consoleContext.openingReferenceChat ? "Opening Chat" : "Chat",
    onSelect: () => {
      if (!selectedReference) return;
      void consoleContext.startReferenceChat({
        anchor: {
          kind: "reference",
          id: selectedReference.id,
          lineageId: selectedReference.lineageId ?? selectedReference.id,
        },
        title: selectedReference.title ?? selectedReference.externalItemId,
        subtitle: selectedReference.corpusId ?? null,
      }).catch((error) => {
        console.error("[ReferencesDesk] Unable to open reference chat", error);
      });
    },
  } : null;
  const selectedReferenceCurationRunStatus = selectedReference
    ? curationRunsByLineage[selectedReference.lineageId ?? selectedReference.id] ?? null
    : null;
  const curationLifecycle = selectedReferenceCurationRunStatus?.lifecycleStatus ?? selectedReferenceCurationRunStatus?.status ?? "";
  const curationInFlight = curationLifecycle === "queued" || curationLifecycle === "running";
  const referenceStartCurationAction: NewsroomDetailAction | null = selectedReference ? {
    ariaLabel: "Start reference re-curation",
    disabled: disabled || curationInFlight,
    icon: <RefreshCwIcon />,
    key: "reference-curation-start",
    label: curationInFlight ? "Curating" : "Curate",
    onSelect: () => onStartCuration(selectedReference),
  } : null;
  const curationMenuActions: NewsroomDetailAction[] = [];
  if (referenceStartCurationAction) curationMenuActions.push(referenceStartCurationAction);
  if (referenceChatAction) curationMenuActions.push(referenceChatAction);
  curationMenuActions.push(referenceKnowledgeQuery.action);
  const selectedLineageId = selectedReference ? selectedReference.lineageId ?? selectedReference.id : null;
  const selectedFilteredReferenceIndex = selectedLineageId
    ? filteredReferences.findIndex((reference) => (reference.lineageId ?? reference.id) === selectedLineageId)
    : -1;
  const referenceMetadataFields = useReferenceMetadataFields(filteredReferences);
  const detail = categoryFilter
    ? `${filteredReferences.length} references classified as ${categoryFilter.label}`
    : `${filteredReferences.length} private corpus items`;
  const statusCounts = countReferencesByStatus(canonicalVisibleReferences);
  const nonPendingCount = (statusCounts.accepted ?? 0) + (statusCounts.rejected ?? 0) + (statusCounts.archived ?? 0);
  const totalReferenceCount = canonicalVisibleReferences.length;
  const hasAnyReferences = totalReferenceCount > 0 || references.length > 0;
  const statusFilterOptions = [
    { key: "__exclude_pending", label: "Reviewed (non-pending)", count: nonPendingCount },
    { key: "", label: "All statuses", count: totalReferenceCount },
    { key: "pending", label: "Pending", count: statusCounts.pending ?? 0 },
    { key: "accepted", label: "Accepted", count: statusCounts.accepted ?? 0 },
    { key: "rejected", label: "Rejected", count: statusCounts.rejected ?? 0 },
    { key: "archived", label: "Archived", count: statusCounts.archived ?? 0 },
  ];
  const processingCounts = countReferencesByProcessing(statusFilteredReferences, referenceAttachments);
  const cards = filteredReferences.map((reference, index) => referenceToNewsroomCard(
    reference,
    index,
    {
      title: referenceMetadataFields.get(reference.id)?.title ?? null,
      subtitle: referenceMetadataFields.get(reference.id)?.subtitle ?? null,
      qualityRating: referenceQualityForList(reference, graph),
    },
  ));
  useEffect(() => {
    if (!selectedLineageId || typeof window === "undefined") return;
    replaceNewsroomDetailUrl("references", selectedLineageId, isDemo);
  }, [isDemo, selectedLineageId]);

  const selectReference = (lineageId: string) => {
    const canonicalLineageId = resolveCanonicalReferenceLineage(references, lineageId);
    setSelectedReferenceLineageId(canonicalLineageId);
    setIsReferenceDetailOpen(true);
    pushNewsroomDetailUrl("references", canonicalLineageId, isDemo);
  };
  useEffect(() => {
    if (!routeReferenceLineageId || isDemo) return;
    const canonicalLineageId = resolveCanonicalReferenceLineage(references, routeReferenceLineageId);
    if (canonicalLineageId === routeReferenceLineageId) return;
    setSelectedReferenceLineageId(canonicalLineageId);
    setIsReferenceDetailOpen(true);
    pushNewsroomDetailUrl("references", canonicalLineageId, isDemo);
  }, [isDemo, references, routeReferenceLineageId]);
  const previousReference = selectedFilteredReferenceIndex > 0 ? filteredReferences[selectedFilteredReferenceIndex - 1] : null;
  const nextReference = selectedFilteredReferenceIndex >= 0 && selectedFilteredReferenceIndex < filteredReferences.length - 1
    ? filteredReferences[selectedFilteredReferenceIndex + 1]
    : null;
  const referenceNavigationActions: NewsroomDetailAction[] = [
    {
      key: "reference-previous",
      label: "Previous",
      disabled: !previousReference,
      onSelect: () => {
        if (!previousReference) return;
        selectReference(previousReference.lineageId ?? previousReference.id);
      },
    },
    {
      key: "reference-next",
      label: "Next",
      disabled: !nextReference,
      onSelect: () => {
        if (!nextReference) return;
        selectReference(nextReference.lineageId ?? nextReference.id);
      },
    },
  ];
  const runReferenceAction = (action: ReferenceCurationAction) => {
    if (!selectedReference) return;
    onReview(
      selectedReference,
      action,
      undefined,
      action === "reject" ? "other" : null,
    );
  };
  const selectedReferenceCuration = selectedReference
    ? resolveReferenceCurationDisplayState(selectedReference, graph)
    : null;
  const selectedReferenceQualityActionState = selectedReference && qualityActionState?.referenceId === selectedReference.id
    ? qualityActionState
    : null;
  const realtimeStatusMessage = formatReferencesRealtimeStatusMessage(realtimeStatus, realtimeError);
  const referenceDetailPending = Boolean(requestedReferenceLineageId) && !selectedReference && !deepLinkReferenceError;
  const referenceDetailPlaceholder = deepLinkReferenceLoading || referenceDetailPending
    ? "Loading reference…"
    : deepLinkReferenceError
      ?? "Select a reference to inspect curation details.";

  return (
    <>
      {realtimeStatusMessage ? (
        <div className="category-steering-alert" role="status" aria-live="polite">
          {realtimeStatusMessage}
        </div>
      ) : null}
      {deepLinkReferenceError ? (
        <div className="category-steering-alert" role="alert">
          {deepLinkReferenceError}
        </div>
      ) : null}
      {deepLinkReferenceLoading ? (
        <div className="category-steering-alert" role="status" aria-live="polite">
          Loading reference…
        </div>
      ) : null}
      <NewsroomListDetailShell
        animatedDetail
        sectionKey="references"
        canExpandDetail={Boolean(selectedReference) || Boolean(requestedReferenceLineageId)}
        detailOpen={isReferenceDetailOpen}
        selectionScrollKey={selectedLineageId}
        actions={[]}
        utilityActions={referenceNavigationActions}
        lede={(
          <NewsroomDeskSectionLede
            headingId="reference-management-title"
            section="references"
            controls={(
              <div className="news-desk-reference-sort-controls" role="group" aria-label="Reference sort order">
                <span className="news-desk-reference-sort-controls__label">Sort</span>
                <button
                  type="button"
                  data-active={orderFilter === "published" || undefined}
                  onClick={() => {
                    setOrderFilter("published");
                    syncReferencesIndexUrl(statusFilter, processingFilter, "published", true);
                  }}
                >
                  Publication date
                </button>
                <button
                  type="button"
                  data-active={orderFilter === "imported" || undefined}
                  onClick={() => {
                    const nextStatus = statusFilter === "__exclude_pending" ? "" : statusFilter;
                    setOrderFilter("imported");
                    if (nextStatus !== statusFilter) setStatusFilter(nextStatus);
                    syncReferencesIndexUrl(nextStatus, processingFilter, "imported", true);
                  }}
                >
                  Date imported
                </button>
              </div>
            )}
          />
        )}
        list={(
          <section className="category-steering-section category-steering-section--lead" aria-label={detail}>
            <NewsroomCardGrid
              cards={cards}
              emptyLabel={hasAnyReferences ? "No references match this filter" : "No private references imported"}
              filterLabel="Curation status"
              filterOptions={statusFilterOptions}
              filterValue={statusFilter}
              metricValue={processingFilter}
              metrics={[
                { key: "", label: "All processing", count: statusFilteredReferences.length },
                { key: "processed", label: "Processed", count: processingCounts.processed },
                { key: "unprocessed", label: "Unprocessed", count: processingCounts.unprocessed },
              ]}
              footerLabel={feed.error ?? undefined}
              hasMore={!isDemo && !categoryFilter && feed.hasMore}
              isLoading={!isDemo && !categoryFilter && feed.isLoading}
              isLoadingMore={feed.isLoadingMore}
              onFilterChange={(value) => {
                setStatusFilter(value);
                syncReferencesIndexUrl(value, processingFilter, orderFilter, true);
              }}
              onLoadMore={feed.loadMore}
              onMetricChange={(value) => {
                setProcessingFilter(value);
                syncReferencesIndexUrl(statusFilter, value, orderFilter, true);
              }}
              sortLabel="Sort"
              sortOptions={[
                { key: "published", label: "Publication date" },
                { key: "imported", label: "Date imported" },
              ]}
              sortValue={orderFilter}
              onSortChange={(value) => {
                const nextOrder = normalizeReferenceIndexOrder(value);
                const nextStatus = nextOrder === "imported" && statusFilter === "__exclude_pending"
                  ? ""
                  : statusFilter;
                setOrderFilter(nextOrder);
                if (nextStatus !== statusFilter) setStatusFilter(nextStatus);
                syncReferencesIndexUrl(nextStatus, processingFilter, nextOrder, true);
              }}
              onSelect={selectReference}
              selectedId={selectedLineageId}
            />
          </section>
        )}
        onCloseDetail={() => {
          setIsReferenceDetailOpen(false);
          setSelectedReferenceLineageId("");
          syncReferencesIndexUrl(statusFilter, processingFilter, orderFilter, true);
        }}
        detail={selectedReference ? (
          <ReferenceDetailPanel
            categories={categories}
            categorySets={categorySets}
            corpora={corpora}
            disabled={disabled}
            graph={graph}
            onCreateInsight={onCreateInsight}
            onMoveCorpus={onMoveCorpus}
            onReview={runReferenceAction}
            onReviewTopicLabel={onReviewTopicLabel}
            onSetQualityRating={onSetQualityRating}
            curation={selectedReferenceCuration}
            curationRunStatus={selectedReferenceCurationRunStatus}
            qualityActionState={selectedReferenceQualityActionState}
            reference={selectedReference}
            semanticRelations={semanticRelations}
            knowledgeQuery={referenceKnowledgeQuery}
            curationMenuActions={curationMenuActions}
          />
        ) : (
          <section
            className="category-steering-section"
            aria-label="Reference detail"
            aria-busy={referenceDetailPending || deepLinkReferenceLoading ? true : undefined}
          >
            <EmptyRow label={referenceDetailPlaceholder} />
          </section>
        )}
      />
      {referenceKnowledgeQuery.dialog}
    </>
  );
}

function NewsroomDeskSectionLede({
  controls,
  headingId,
  headline,
  lede,
  section,
}: {
  controls?: ReactNode;
  headingId: string;
  headline?: string;
  lede?: string;
  section: NewsDeskTab;
}) {
  return (
    <section className="news-desk-lede news-desk-assignment-lede" aria-labelledby={headingId}>
      <div>
        <h2 id={headingId}>{headline ?? formatDeskSectionHeadline(section)}</h2>
        <p>{lede ?? formatDeskSectionLede(section)}</p>
      </div>
      {controls ?? null}
    </section>
  );
}

function InsightsDeskView({
  graph,
  initialThreadId = null,
  isDemo = false,
  messages,
  summary,
}: {
  graph: SemanticGraph;
  initialThreadId?: string | null;
  isDemo?: boolean;
  messages: MessageRecord[];
  summary?: NewsroomSummaryRecord | null;
}) {
  const pathname = usePathname();
  const pathnameThreadId = useMemo(
    () => parseInsightThreadIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const resolvedInitialThreadId = initialThreadId ?? pathnameThreadId ?? "";
  const forumMessageAnchorId = useForumMessageAnchorId();
  const [domainFilter, setDomainFilter] = useState(() => {
    if (typeof window === "undefined") return "";
    return readInsightsIndexFilters(new URLSearchParams(window.location.search)).domain;
  });
  const [threads, setThreads] = useState<ForumThreadWithMessages[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [threadsError, setThreadsError] = useState<string | null>(null);
  const [nextToken, setNextToken] = useState<string | null>(null);
  const [selectedThreadId, setSelectedThreadId] = useState(resolvedInitialThreadId);
  const [forumView, setForumView] = useState<ForumViewState>(
    resolvedInitialThreadId ? { mode: "thread", threadId: resolvedInitialThreadId } : { mode: "index" },
  );
  const [replyParentId, setReplyParentId] = useState("");
  const [composeSummary, setComposeSummary] = useState("");
  const [composeContent, setComposeContent] = useState("");
  const [composeError, setComposeError] = useState<string | null>(null);
  const [deletingMessageId, setDeletingMessageId] = useState("");

  const syncInsightsIndexUrl = useCallback((nextDomain: string, replace = true) => {
    if (isDemo || forumView.mode === "thread") return;
    syncBrowserNewsroomIndexUrl("insights", effectiveInsightsIndexFilters({ domain: nextDomain }), { replace });
  }, [forumView.mode, isDemo]);

  useEffect(() => {
    if (isDemo || forumView.mode === "thread") return;
    syncInsightsIndexUrl(domainFilter, true);
  }, [domainFilter, forumView.mode, isDemo, syncInsightsIndexUrl]);

  const refreshThreads = useCallback(async (options?: { append?: boolean; token?: string | null }) => {
    if (isDemo) {
      const demoThreads = messages
        .filter((message) => message.messageKind === "insight")
        .filter((message) => !domainFilter || message.messageDomain === domainFilter)
        .map((message) => buildDemoInsightForumThread(message, messages));
      setThreads(demoThreads);
      setThreadsError(null);
      setNextToken(null);
      return;
    }
    setThreadsLoading(true);
    try {
      const result = await loadInsightForumThreads({
        domain: domainFilter,
        nextToken: options?.token ?? null,
        includeMessages: true,
      });
      setThreads((current) => (options?.append ? [...current, ...result.threads] : result.threads));
      setNextToken(result.nextToken);
      setThreadsError(null);
      setSelectedThreadId((current) => (current && result.threads.some((thread) => thread.id === current) ? current : current));
    } catch (error) {
      setThreads([]);
      setThreadsError(error instanceof Error ? error.message : "Could not load insight threads.");
      setNextToken(null);
    } finally {
      setThreadsLoading(false);
    }
  }, [domainFilter, isDemo, messages]);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  useEffect(() => {
    if (!resolvedInitialThreadId || threadsLoading) return;
    if (!threads.some((thread) => thread.id === resolvedInitialThreadId)) return;
    if (selectedThreadId === resolvedInitialThreadId && forumView.mode === "thread") return;
    setSelectedThreadId(resolvedInitialThreadId);
    setForumView({ mode: "thread", threadId: resolvedInitialThreadId });
  }, [forumView.mode, resolvedInitialThreadId, selectedThreadId, threads, threadsLoading]);

  useEffect(() => {
    const handlePopState = () => {
      const route = readCurrentForumRoute();
      if (route.surface === "insight_forum" && route.threadId) {
        setSelectedThreadId(route.threadId);
        setForumView({ mode: "thread", threadId: route.threadId });
        return;
      }
      setSelectedThreadId("");
      setForumView({ mode: "index" });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const selectedThread = threads.find((thread) => thread.id === selectedThreadId) ?? null;
  const domainOptions = useMemo(() => {
    const domains = new Set<string>();
    for (const message of messages) {
      if (message.messageKind === "insight" && message.messageDomain) domains.add(message.messageDomain);
    }
    for (const thread of threads) {
      if (thread.sectionKey) domains.add(thread.sectionKey);
    }
    return sortedCountOptions(
      Object.fromEntries([...domains].map((domain) => [domain, threads.filter((thread) => thread.sectionKey === domain).length])),
    );
  }, [messages, threads]);

  const openThread = useCallback((threadId: string, options?: { messageId?: string | null; replace?: boolean }) => {
    setSelectedThreadId(threadId);
    setForumView({ mode: "thread", threadId });
    pushInsightThreadUrl(threadId, {
      demo: isDemo,
      messageId: options?.messageId,
      replace: options?.replace,
    });
  }, [isDemo]);

  const closeThread = useCallback(() => {
    setSelectedThreadId("");
    setForumView({ mode: "index" });
    pushInsightThreadUrl(null, { demo: isDemo, replace: true });
  }, [isDemo]);

  const postThreadMessage = useCallback(async () => {
    if (!selectedThread) return;
    const content = composeContent.trim();
    if (!content) {
      setComposeError("Message content is required.");
      return;
    }
    const summary = composeSummary.trim() || content.slice(0, 120);
    setComposeError(null);
    try {
      await appendInsightThreadReplyRecord({
        threadId: selectedThread.id,
        summary,
        content,
        role: "human",
        authorLabel: "human-editor",
        parentMessageId: replyParentId || undefined,
      });
      setComposeSummary("");
      setComposeContent("");
      setReplyParentId("");
      await refreshThreads();
      const reloaded = await loadInsightForumThreadById(selectedThread.id, { includeMessages: true });
      if (reloaded) {
        setThreads((current) => current.map((thread) => (thread.id === reloaded.id ? reloaded : thread)));
      }
      setForumView({ mode: "thread", threadId: selectedThread.id });
    } catch (error) {
      setComposeError(error instanceof Error ? error.message : "Could not post thread message.");
    }
  }, [composeContent, composeSummary, refreshThreads, replyParentId, selectedThread]);

  const deleteThreadMessage = useCallback(async (threadId: string, messageId: string) => {
    setDeletingMessageId(messageId);
    try {
      await deleteInsightThreadMessageRecord({ threadId, messageId });
      if (replyParentId === messageId) setReplyParentId("");
      await refreshThreads();
      const reloaded = await loadInsightForumThreadById(threadId, { includeMessages: true });
      if (reloaded) {
        setThreads((current) => current.map((thread) => (thread.id === reloaded.id ? reloaded : thread)));
      }
      setComposeError(null);
    } catch (error) {
      setComposeError(error instanceof Error ? error.message : "Could not delete message.");
    } finally {
      setDeletingMessageId("");
    }
  }, [refreshThreads, replyParentId]);

  const insightKnowledgeQuery = useNewsroomKnowledgeContext(selectedThread ? {
    anchor: { kind: "message", id: selectedThread.id, lineageId: selectedThread.id },
    title: selectedThread.title ?? "Insight thread",
    subtitle: selectedThread.sectionKey ?? "insight",
  } : null);

  return (
    <>
      <NewsroomListDetailShell
        sectionKey="insights"
        canExpandDetail={forumView.mode === "thread" && Boolean(forumView.threadId)}
        detailOpen={forumView.mode === "thread" && Boolean(forumView.threadId)}
        selectionScrollKey={forumView.mode === "thread" ? forumView.threadId : null}
        utilityActions={[insightKnowledgeQuery.action]}
        lede={(
          <NewsroomDeskSectionLede
            headingId="insights-forum-title"
            section="insights"
            headline="Insights"
            lede="Recent research insights in reverse chronological order. Each insight opens a forum thread for discussion and refinement."
            controls={(
              <div className="news-desk-reference-sort-controls" role="group" aria-label="Insight domain filter">
                <span className="news-desk-reference-sort-controls__label">Domain</span>
                <button
                  type="button"
                  data-active={!domainFilter || undefined}
                  onClick={() => {
                    setDomainFilter("");
                    syncInsightsIndexUrl("", true);
                  }}
                >
                  All
                </button>
                <button
                  type="button"
                  data-active={domainFilter === "knowledge" || undefined}
                  onClick={() => {
                    setDomainFilter("knowledge");
                    syncInsightsIndexUrl("knowledge", true);
                  }}
                >
                  Knowledge
                </button>
                <button
                  type="button"
                  data-active={domainFilter === "assignment_work" || undefined}
                  onClick={() => {
                    setDomainFilter("assignment_work");
                    syncInsightsIndexUrl("assignment_work", true);
                  }}
                >
                  Assignment work
                </button>
              </div>
            )}
          />
        )}
        list={(
          <section className="category-steering-section category-steering-section--lead" aria-label="Insight forum threads">
            <ForumThreadIndex
              threads={threads}
              sections={[]}
              isLoading={threadsLoading}
              error={threadsError}
              emptyLabel="No insight threads match this filter."
              variant="insight"
              toolbar={domainOptions.length > 2 ? (
                <div className="news-desk-forum-toolbar">
                  <select
                    aria-label="Insight domain"
                    value={domainFilter}
                    onChange={(event) => {
                      setDomainFilter(event.target.value);
                      syncInsightsIndexUrl(event.target.value, true);
                    }}
                  >
                    <option value="">All domains ({threads.length})</option>
                    {domainOptions.map((option) => (
                      <option key={option.key} value={option.key}>{option.key} ({option.count})</option>
                    ))}
                  </select>
                  {nextToken ? (
                    <button type="button" disabled={threadsLoading} onClick={() => void refreshThreads({ append: true, token: nextToken })}>
                      Load more
                    </button>
                  ) : null}
                </div>
              ) : nextToken ? (
                <div className="news-desk-forum-toolbar">
                  <button type="button" disabled={threadsLoading} onClick={() => void refreshThreads({ append: true, token: nextToken })}>
                    Load more
                  </button>
                </div>
              ) : null}
              onOpenThread={(threadId) => openThread(threadId)}
            />
          </section>
        )}
        detail={forumView.mode === "thread" && selectedThread ? (
          <ForumThreadView
            thread={selectedThread}
            sections={[]}
            replyParentId={replyParentId}
            composeSummary={composeSummary}
            composeContent={composeContent}
            composeError={composeError}
            focusMessageId={forumMessageAnchorId}
            isDemo={isDemo}
            variant="insight"
            onBack={closeThread}
            onReplyTarget={(messageId) => {
              setReplyParentId(messageId);
              pushInsightThreadUrl(selectedThread.id, { demo: isDemo, messageId, replace: true });
            }}
            onClearReplyTarget={() => {
              setReplyParentId("");
              pushInsightThreadUrl(selectedThread.id, { demo: isDemo, replace: true });
            }}
            onSummaryChange={setComposeSummary}
            onContentChange={setComposeContent}
            onSubmit={() => void postThreadMessage()}
            onDeleteMessage={(messageId) => {
              if (!selectedThread || deletingMessageId === messageId) return;
              void deleteThreadMessage(selectedThread.id, messageId);
            }}
            deletingMessageId={deletingMessageId}
          />
        ) : forumView.mode === "thread" ? (
          <section className="category-steering-section">
            <SectionHeader title="Thread Unavailable" detail="Insights" />
            <EmptyRow label="That insight thread is not available. Return to the index or adjust filters." />
          </section>
        ) : null}
      />
      {insightKnowledgeQuery.dialog}
    </>
  );
}

function buildDemoInsightForumThread(root: MessageRecord, allMessages: MessageRecord[]): ForumThreadWithMessages {
  const replies = allMessages.filter((message) => (
    message.threadId === root.id
    && message.id !== root.id
    && String(message.status || "active") === "active"
  ));
  const messages = [root, ...replies].sort(
    (left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0),
  );
  const lastMessage = messages.at(-1) ?? root;
  return {
    id: root.id,
    threadKind: "insight_forum",
    status: "active",
    title: root.summary ?? "Insight",
    summary: root.messageDomain ?? null,
    primaryAnchorKind: "message",
    primaryAnchorId: root.id,
    primaryAnchorLineageId: root.id,
    primaryAnchorKey: `message#${root.id}`,
    createdByLabel: root.authorLabel ?? null,
    messageCount: messages.length,
    lastMessageId: lastMessage.id,
    lastMessageAt: lastMessage.updatedAt ?? lastMessage.createdAt,
    metadata: metadataRecord(root.metadata),
    createdAt: root.createdAt,
    updatedAt: lastMessage.updatedAt ?? lastMessage.createdAt,
    newsroomFeedKey: "messages",
    messages,
    scope: "insight",
    sectionKey: root.messageDomain ?? null,
  };
}

function MessagesDeskView({
  assignments,
  graph,
  initialForumThreadId = null,
  initialMessageId,
  isDemo = false,
  messages,
  newsroomSections,
  summary,
}: {
  assignments: AssignmentRecord[];
  graph: SemanticGraph;
  initialForumThreadId?: string | null;
  initialMessageId?: string | null;
  isDemo?: boolean;
  messages: MessageRecord[];
  newsroomSections: NewsroomSectionRecord[];
  summary?: NewsroomSummaryRecord | null;
}) {
  const resolvedInitialForumThreadId = initialForumThreadId
    ?? (isForumThreadId(initialMessageId) ? initialMessageId : null);
  const forumMessageAnchorId = useForumMessageAnchorId();
  const [kindFilter, setKindFilter] = useState(() => {
    if (resolvedInitialForumThreadId) return "__forum";
    if (typeof window === "undefined") return "";
    return readMessagesIndexFilters(new URLSearchParams(window.location.search)).kind;
  });
  const [domainFilter, setDomainFilter] = useState(() => {
    if (typeof window === "undefined") return "";
    return readMessagesIndexFilters(new URLSearchParams(window.location.search)).domain;
  });
  const [selectedMessageId, setSelectedMessageId] = useState(initialMessageId ?? "");
  const [isMessageDetailOpen, setIsMessageDetailOpen] = useState(Boolean(initialMessageId));
  const [consoleThreads, setConsoleThreads] = useState<ConsoleThreadSummary[]>([]);
  const [consoleThreadsError, setConsoleThreadsError] = useState<string | null>(null);
  const [selectedForumEditionId, setSelectedForumEditionId] = useState("");
  const [selectedForumSectionId, setSelectedForumSectionId] = useState("");
  const [forumScopeFilter, setForumScopeFilter] = useState<"all" | "edition" | "section">("all");
  const [forumActivityFilter, setForumActivityFilter] = useState<"active" | "all">("active");
  const [forumThreads, setForumThreads] = useState<ForumThreadWithMessages[]>([]);
  const [forumThreadsLoading, setForumThreadsLoading] = useState(false);
  const [forumThreadsError, setForumThreadsError] = useState<string | null>(null);
  const [selectedForumThreadId, setSelectedForumThreadId] = useState("");
  const [forumView, setForumView] = useState<ForumViewState>({ mode: "index" });
  const [forumComposeSummary, setForumComposeSummary] = useState("");
  const [forumComposeContent, setForumComposeContent] = useState("");
  const [forumReplyParentId, setForumReplyParentId] = useState("");
  const [forumComposeError, setForumComposeError] = useState<string | null>(null);
  const [newForumThreadDraft, setNewForumThreadDraft] = useState<ForumNewThreadDraft>(createDefaultForumNewThreadDraft(""));
  const [newForumThreadOpen, setNewForumThreadOpen] = useState(false);
  const [newForumThreadError, setNewForumThreadError] = useState<string | null>(null);
  const [deletingForumMessageId, setDeletingForumMessageId] = useState("");
  const messageKind = kindFilter === "__chat_detail" ? "console_chat_turn" : kindFilter;
  const isForumMode = kindFilter === "__forum";
  const syncMessagesIndexUrl = useCallback((nextKind: string, nextDomain: string, replace = true) => {
    if (isDemo || isForumMode || isMessageDetailOpen) return;
    syncBrowserNewsroomIndexUrl(
      "messages",
      effectiveMessagesIndexFilters({ kind: nextKind, domain: nextDomain }),
      { replace },
    );
  }, [isDemo, isForumMode, isMessageDetailOpen]);
  useEffect(() => {
    if (isDemo || isForumMode || isMessageDetailOpen) return;
    syncMessagesIndexUrl(kindFilter, domainFilter, true);
  }, [domainFilter, isDemo, isForumMode, isMessageDetailOpen, kindFilter, syncMessagesIndexUrl]);
  const feed = useNewsroomPagedRows({
    initialItems: messages,
    enabled: !isDemo && kindFilter !== "__chat_sessions" && !isForumMode,
    resetKey: `messages:${kindFilter}:${domainFilter}`,
    loadPage: (nextToken) => loadNewsroomMessagePage({
      kind: messageKind,
      domain: domainFilter,
      nextToken,
    }),
  });
  useEffect(() => {
    if (isDemo || kindFilter !== "__chat_sessions") return;
    let active = true;
    void listConsoleThreads(100)
      .then((threads) => {
        if (!active) return;
        setConsoleThreads(threads);
        setConsoleThreadsError(null);
      })
      .catch((error) => {
        if (!active) return;
        setConsoleThreadsError(error instanceof Error ? error.message : "Unable to load chat sessions.");
      });
    return () => {
      active = false;
    };
  }, [isDemo, kindFilter]);
  const [messageOverviewEditions, setMessageOverviewEditions] = useState<ResolvedOverviewEdition[]>([]);
  useEffect(() => {
    if (isDemo) {
      setMessageOverviewEditions([]);
      return;
    }
    let active = true;
    void loadEditorOverviewEditionData()
      .then((data) => {
        if (!active) return;
        setMessageOverviewEditions(resolveOverviewEditions({
          editions: data.editions,
          editionSlots: data.editionSlots,
          assignments: data.assignments,
        }));
      })
      .catch(() => {
        if (!active) return;
        setMessageOverviewEditions(resolveOverviewEditions({
          editions: [],
          editionSlots: [],
          assignments,
        }));
      });
    return () => {
      active = false;
    };
  }, [assignments, isDemo]);
  const availableSections = useMemo(
    () => sortNewsroomSections(newsroomSections).filter((section) => section.enabled !== false),
    [newsroomSections],
  );
  useEffect(() => {
    if (!messageOverviewEditions.length) {
      setSelectedForumEditionId("");
      return;
    }
    if (selectedForumEditionId && messageOverviewEditions.some((edition) => edition.editionId === selectedForumEditionId)) {
      return;
    }
    const preferred = messageOverviewEditions.find((edition) => edition.isNearestUpcoming) ?? messageOverviewEditions[0];
    setSelectedForumEditionId(preferred.editionId);
  }, [messageOverviewEditions, selectedForumEditionId]);
  useEffect(() => {
    if (!availableSections.length) {
      setSelectedForumSectionId("");
      setNewForumThreadDraft((current) => ({ ...current, sectionId: "" }));
      return;
    }
    if (!selectedForumSectionId || !availableSections.some((section) => section.id === selectedForumSectionId)) {
      setSelectedForumSectionId(availableSections[0].id);
    }
    setNewForumThreadDraft((current) => (
      current.sectionId
        ? current
        : { ...current, sectionId: availableSections[0].id }
    ));
  }, [availableSections, selectedForumSectionId]);
  const refreshForumThreads = useCallback(async () => {
    if (!selectedForumEditionId) {
      setForumThreads([]);
      setForumThreadsError(null);
      return;
    }
    setForumThreadsLoading(true);
    try {
      const sectionIdForQuery = forumScopeFilter === "section" ? selectedForumSectionId : "";
      const sectionForQuery = availableSections.find((section) => section.id === sectionIdForQuery) ?? null;
      const result = await loadEditionForumThreads({
        editionId: selectedForumEditionId,
        sectionId: sectionIdForQuery || undefined,
        sectionKey: sectionForQuery?.id ?? undefined,
        includeMessages: true,
        status: forumActivityFilter === "active" ? "active" : "",
      });
      const merged = [...result.editionThreads, ...result.sectionThreads]
        .sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")));
      setForumThreads(merged);
      setForumThreadsError(null);
      setSelectedForumThreadId((current) => (current && merged.some((thread) => thread.id === current) ? current : ""));
    } catch (error) {
      setForumThreads([]);
      setForumThreadsError(error instanceof Error ? error.message : "Could not load edition forum threads.");
    } finally {
      setForumThreadsLoading(false);
    }
  }, [availableSections, forumActivityFilter, forumScopeFilter, selectedForumEditionId, selectedForumSectionId]);
  useEffect(() => {
    if (!isForumMode || isDemo) return;
    void refreshForumThreads();
  }, [isDemo, isForumMode, refreshForumThreads]);
  useEffect(() => {
    if (!isForumMode) return;
    const threadId = resolvedInitialForumThreadId ?? readCurrentForumRoute().threadId;
    if (!threadId || forumThreadsLoading) return;
    if (!forumThreads.some((thread) => thread.id === threadId)) return;
    if (selectedForumThreadId === threadId && forumView.mode === "thread") return;
    setSelectedForumThreadId(threadId);
    setForumView({ mode: "thread", threadId });
  }, [
    forumThreads,
    forumThreadsLoading,
    forumView.mode,
    isForumMode,
    resolvedInitialForumThreadId,
    selectedForumThreadId,
  ]);

  useEffect(() => {
    if (!isForumMode) return;
    const handlePopState = () => {
      const route = readCurrentForumRoute();
      if (route.threadId) {
        setSelectedForumThreadId(route.threadId);
        setForumView({ mode: "thread", threadId: route.threadId });
        return;
      }
      setSelectedForumThreadId("");
      setForumView({ mode: "index" });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [isForumMode]);
  const feedMessages = isDemo ? messages : feed.items;
  const messageKindCounts = summary?.facets?.messages?.byKind ?? summary?.messageKindCounts ?? countMessagesBy(messages, "messageKind");
  const messageDomainCounts = summary?.facets?.messages?.byDomain ?? summary?.messageDomainCounts ?? countMessagesBy(messages, "messageDomain");
  const messageKinds = useMemo(() => sortedCountOptions(messageKindCounts).map((option) => option.key), [messageKindCounts]);
  const messageDomains = useMemo(() => sortedCountOptions(messageDomainCounts).map((option) => option.key), [messageDomainCounts]);
  const chatSessionMessages = useMemo(() => consoleThreads.map(consoleThreadToMessageRecord), [consoleThreads]);
  const forumSectionKeyByThreadId = useMemo(() => {
    const map = new Map<string, string>();
    for (const thread of forumThreads) {
      const sectionKey = normalizeForumThreadSectionKey(thread);
      if (sectionKey) map.set(thread.id, sectionKey);
    }
    return map;
  }, [forumThreads]);
  const filteredForumThreads = useMemo(() => forumThreads.filter((thread) => {
    if (forumScopeFilter === "edition" && thread.scope !== "edition") return false;
    if (forumScopeFilter === "section" && thread.scope !== "section") return false;
    if (forumScopeFilter === "section" && selectedForumSectionId) {
      const selectedSection = availableSections.find((section) => section.id === selectedForumSectionId) ?? null;
      if (selectedSection) {
        const threadSectionKey = forumSectionKeyByThreadId.get(thread.id) ?? "";
        if (threadSectionKey && threadSectionKey !== selectedSection.id) return false;
      }
    }
    if (forumActivityFilter === "active" && thread.status !== "active") return false;
    return true;
  }), [availableSections, forumActivityFilter, forumScopeFilter, forumSectionKeyByThreadId, forumThreads, selectedForumSectionId]);
  const selectedForumThread = filteredForumThreads.find((thread) => thread.id === selectedForumThreadId) ?? null;
  const visibleMessages = useMemo(() => {
    if (kindFilter === "__chat_sessions") return chatSessionMessages;
    return feedMessages
      .filter((message) => !messageKind || message.messageKind === messageKind)
      .filter((message) => !domainFilter || message.messageDomain === domainFilter)
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }, [chatSessionMessages, domainFilter, feedMessages, kindFilter, messageKind]);
  const selectedMessage = visibleMessages.find((message) => message.id === selectedMessageId)
    ?? (initialMessageId ? messages.find((message) => message.id === initialMessageId) : null)
    ?? visibleMessages[0]
    ?? null;
  const selected = selectedMessage ? graph.resolve("message", selectedMessage.id) : null;
  const selectedForumMessage = selectedForumThread
    ? [...(selectedForumThread.messages ?? [])]
      .sort((left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0))
      .at(-1) ?? null
    : null;
  const selectedEntity = isForumMode
    ? (selectedForumMessage ? graph.resolve("message", selectedForumMessage.id) : null)
    : selected;
  const messageKnowledgeQuery = useNewsroomKnowledgeContext(selectedMessage ? {
    anchor: { kind: "message", id: selectedMessage.id },
    title: selectedMessage.summary ?? "Stored message payload",
    subtitle: selectedMessage.messageKind,
  } : null);
  const forumKnowledgeQuery = useNewsroomKnowledgeContext(selectedForumMessage ? {
    anchor: { kind: "message", id: selectedForumMessage.id },
    title: selectedForumThread?.title ?? selectedForumMessage.summary ?? "Forum thread",
    subtitle: selectedForumMessage.messageKind,
  } : null);
  const cards = visibleMessages.map((message, index) => messageToNewsroomCard(message, index));
  const totalMessageCount = summaryCountFromRecord(summary, "messages") || messages.length;
  const metrics = [
    { key: "", label: "All", count: totalMessageCount },
    ...messageDomains.slice(0, 4).map((domain) => ({ key: domain, label: domain, count: messageDomainCounts[domain] ?? 0 })),
  ];
  const selectMessage = (id: string) => {
    setSelectedMessageId(id);
    setIsMessageDetailOpen(true);
    pushNewsroomDetailUrl("messages", id, isDemo);
  };
  const openForumThread = (threadId: string, options?: { messageId?: string | null; replace?: boolean }) => {
    setSelectedForumThreadId(threadId);
    setForumView({ mode: "thread", threadId });
    setIsMessageDetailOpen(true);
    pushForumThreadUrl(threadId, {
      demo: isDemo,
      messageId: options?.messageId,
      replace: options?.replace,
    });
  };

  const closeForumThread = () => {
    setSelectedForumThreadId("");
    setForumView({ mode: "index" });
    pushForumThreadUrl(null, { demo: isDemo, replace: true });
  };
  const submitNewForumThread = async () => {
    if (!selectedForumEditionId) return;
    const title = newForumThreadDraft.title.trim();
    const content = newForumThreadDraft.content.trim();
    if (!title) {
      setNewForumThreadError("Thread title is required.");
      return;
    }
    if (!content) {
      setNewForumThreadError("Thread body is required.");
      return;
    }
    try {
      let threadId = "";
      if (newForumThreadDraft.scope === "section") {
        const sectionId = String(newForumThreadDraft.sectionId || selectedForumSectionId || "").trim();
        const section = availableSections.find((entry) => entry.id === sectionId) ?? null;
        if (!section) {
          setNewForumThreadError("Section is required for section threads.");
          return;
        }
        const created = await createSectionForumThreadRecord({
          editionId: selectedForumEditionId,
          sectionId: section.id,
          sectionKey: section.id,
          sectionTitle: section.title,
          title,
          actorLabel: "human-editor",
        });
        threadId = created.thread.id;
      } else {
        const ensured = await ensureEditionForumThreadRecord({
          editionId: selectedForumEditionId,
          actorLabel: "human-editor",
        });
        threadId = ensured.thread.id;
      }
      await appendForumThreadMessageRecord({
        threadId,
        summary: title,
        content,
        role: "human",
        authorLabel: "human-editor",
      });
      await refreshForumThreads();
      setNewForumThreadDraft(createDefaultForumNewThreadDraft(selectedForumSectionId || availableSections[0]?.id || ""));
      setNewForumThreadError(null);
      setNewForumThreadOpen(false);
      openForumThread(threadId, { replace: true });
    } catch (error) {
      setNewForumThreadError(error instanceof Error ? error.message : "Could not create thread.");
    }
  };
  const submitForumMessage = async () => {
    if (!selectedForumThread) return;
    const summary = forumComposeSummary.trim() || forumComposeContent.trim().slice(0, 120) || "Forum reply";
    const content = forumComposeContent.trim();
    if (!content) {
      setForumComposeError("Message content is required.");
      return;
    }
    setForumComposeError(null);
    try {
      await appendForumThreadMessageRecord({
        threadId: selectedForumThread.id,
        summary,
        content,
        role: "human",
        authorLabel: "human-editor",
        parentMessageId: forumReplyParentId || undefined,
      });
      setForumComposeSummary("");
      setForumComposeContent("");
      setForumReplyParentId("");
      await refreshForumThreads();
      setForumView({ mode: "thread", threadId: selectedForumThread.id });
    } catch (error) {
      setForumComposeError(error instanceof Error ? error.message : "Could not append message.");
    }
  };
  const deleteForumMessage = async (threadId: string, messageId: string) => {
    setDeletingForumMessageId(messageId);
    try {
      await deleteForumThreadMessageRecord({ threadId, messageId });
      if (forumReplyParentId === messageId) setForumReplyParentId("");
      await refreshForumThreads();
      setForumComposeError(null);
    } catch (error) {
      setForumComposeError(error instanceof Error ? error.message : "Could not delete message.");
    } finally {
      setDeletingForumMessageId("");
    }
  };
  return (
    <>
      <NewsroomListDetailShell
        animatedDetail
        sectionKey="messages"
        canExpandDetail={Boolean(isForumMode ? (forumView.mode === "thread" && forumView.threadId) : selectedMessage)}
        detailOpen={isForumMode ? (forumView.mode === "thread" && Boolean(forumView.threadId)) : isMessageDetailOpen}
        selectionScrollKey={(isForumMode ? (forumView.mode === "thread" ? forumView.threadId : null) : selectedMessage?.id) ?? null}
        utilityActions={[isForumMode ? forumKnowledgeQuery.action : messageKnowledgeQuery.action]}
        lede={(
          <section className="news-desk-lede news-desk-assignment-lede" aria-labelledby="message-management-title">
            <div>
              <h2 id="message-management-title">{formatDeskSectionHeadline("messages")}</h2>
              <p>{formatDeskSectionLede("messages")}</p>
            </div>
          </section>
        )}
        list={(
          <section className="category-steering-section category-steering-section--lead" aria-label="Messages">
            {isForumMode ? (
              <ForumThreadIndex
                threads={filteredForumThreads}
                sections={availableSections}
                isLoading={forumThreadsLoading}
                error={forumThreadsError}
                emptyLabel="No forum threads for this edition/filter."
                toolbar={(
                  <div className="news-desk-forum-toolbar">
                    <select
                      aria-label="Forum edition"
                      value={selectedForumEditionId}
                      onChange={(event) => setSelectedForumEditionId(event.target.value)}
                    >
                      {messageOverviewEditions.length ? messageOverviewEditions.map((edition) => (
                        <option key={edition.editionId} value={edition.editionId}>{edition.label}</option>
                      )) : <option value="">No editions found</option>}
                    </select>
                    <select
                      aria-label="Forum scope"
                      value={forumScopeFilter}
                      onChange={(event) => setForumScopeFilter((event.target.value as "all" | "edition" | "section"))}
                    >
                      <option value="all">All scopes</option>
                      <option value="edition">Edition</option>
                      <option value="section">Section</option>
                    </select>
                    <select
                      aria-label="Forum section"
                      value={selectedForumSectionId}
                      onChange={(event) => {
                        setSelectedForumSectionId(event.target.value);
                        setNewForumThreadDraft((current) => ({ ...current, sectionId: event.target.value }));
                      }}
                      disabled={!availableSections.length}
                    >
                      {availableSections.length ? availableSections.map((section) => (
                        <option key={section.id} value={section.id}>{section.title}</option>
                      )) : <option value="">No sections</option>}
                    </select>
                    <select
                      aria-label="Forum status"
                      value={forumActivityFilter}
                      onChange={(event) => setForumActivityFilter((event.target.value as "active" | "all"))}
                    >
                      <option value="active">Active</option>
                      <option value="all">All</option>
                    </select>
                    <button type="button" disabled={!selectedForumEditionId} onClick={() => setNewForumThreadOpen((value) => !value)}>
                      {newForumThreadOpen ? "Close New Thread" : "New Thread"}
                    </button>
                    <button type="button" onClick={() => setKindFilter("")}>Back to Messages</button>
                  </div>
                )}
                composer={newForumThreadOpen ? (
                  <ForumThreadComposer
                    draft={newForumThreadDraft}
                    sections={availableSections}
                    error={newForumThreadError}
                    onChange={setNewForumThreadDraft}
                    onCancel={() => {
                      setNewForumThreadOpen(false);
                      setNewForumThreadError(null);
                    }}
                    onSubmit={() => void submitNewForumThread()}
                  />
                ) : null}
                onOpenThread={openForumThread}
              />
            ) : (
              <NewsroomCardGrid
                cards={cards}
                emptyLabel="No private messages recorded"
                filterLabel="Message kind"
                filterOptions={[
                  { key: "__forum", label: "Forum threads", count: forumThreads.length || undefined },
                  { key: "", label: "All kinds", count: totalMessageCount },
                  { key: "__chat_sessions", label: "Chat sessions", count: consoleThreads.length || undefined },
                  { key: "__chat_detail", label: "Chat detail", count: messageKindCounts.console_chat_turn ?? 0 },
                  ...messageKinds.map((kind) => ({ key: kind, label: kind, count: messageKindCounts[kind] ?? 0 })),
                ]}
                filterValue={kindFilter}
                metricValue={domainFilter}
                metrics={metrics}
                footerLabel={consoleThreadsError ?? feed.error ?? undefined}
                hasMore={!isDemo && kindFilter !== "__chat_sessions" && feed.hasMore}
                isLoadingMore={feed.isLoadingMore}
                onFilterChange={(value) => {
                  setKindFilter(value);
                  syncMessagesIndexUrl(value, domainFilter, true);
                }}
                onLoadMore={feed.loadMore}
                onMetricChange={(value) => {
                  setDomainFilter(value);
                  syncMessagesIndexUrl(kindFilter, value, true);
                }}
                onSelect={selectMessage}
                selectedId={selectedMessage?.id ?? null}
              />
            )}
          </section>
        )}
        onCloseDetail={() => {
          if (isForumMode) {
            closeForumThread();
            return;
          }
          setIsMessageDetailOpen(false);
          syncMessagesIndexUrl(kindFilter, domainFilter, true);
        }}
        detail={isForumMode ? (
          (forumView.mode === "thread" && selectedForumThread ? (
            <ForumThreadView
              thread={selectedForumThread}
              sections={availableSections}
              replyParentId={forumReplyParentId}
              composeSummary={forumComposeSummary}
              composeContent={forumComposeContent}
              composeError={forumComposeError}
              focusMessageId={forumMessageAnchorId}
              isDemo={isDemo}
              onBack={closeForumThread}
              onReplyTarget={(messageId) => {
                setForumReplyParentId(messageId);
                pushForumThreadUrl(selectedForumThread.id, { demo: isDemo, messageId, replace: true });
              }}
              onDeleteMessage={(messageId) => {
                if (!selectedForumThread || deletingForumMessageId === messageId) return;
                void deleteForumMessage(selectedForumThread.id, messageId);
              }}
              onClearReplyTarget={() => {
                setForumReplyParentId("");
                pushForumThreadUrl(selectedForumThread.id, { demo: isDemo, replace: true });
              }}
              onSummaryChange={setForumComposeSummary}
              onContentChange={setForumComposeContent}
              onSubmit={() => void submitForumMessage()}
              deletingMessageId={deletingForumMessageId}
            />
          ) : forumView.mode === "thread" ? (
            <section className="category-steering-section">
              <SectionHeader title="Thread Unavailable" detail="Forum" />
              <EmptyRow label="That thread is not available under the current filters. Return to Threads and adjust filters." />
              <button type="button" onClick={closeForumThread}>Back to Threads</button>
            </section>
          ) : <SemanticDetailPanel graph={graph} selected={selectedEntity} knowledgeQuery={forumKnowledgeQuery} />)
        ) : (selectedMessage
          ? <MessageDetailPanel graph={graph} message={selectedMessage} selected={selected} knowledgeQuery={messageKnowledgeQuery} />
          : <SemanticDetailPanel graph={graph} selected={selected} knowledgeQuery={messageKnowledgeQuery} />)}
      />
      {isForumMode ? forumKnowledgeQuery.dialog : messageKnowledgeQuery.dialog}
    </>
  );
}

function useForumMessageAnchorId(): string | null {
  const [messageId, setMessageId] = useState<string | null>(null);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setMessageId(parseForumMessageAnchorFromHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  return messageId;
}

type ForumViewState = { mode: "index" } | { mode: "thread"; threadId: string };

type ForumNewThreadDraft = {
  title: string;
  content: string;
  scope: "edition" | "section";
  sectionId: string;
};

function createDefaultForumNewThreadDraft(sectionId = ""): ForumNewThreadDraft {
  return {
    title: "",
    content: "",
    scope: "edition",
    sectionId,
  };
}

function ForumThreadIndex({
  threads,
  sections,
  isLoading,
  error,
  emptyLabel,
  toolbar,
  composer,
  variant = "edition",
  onOpenThread,
}: {
  threads: ForumThreadWithMessages[];
  sections: NewsroomSectionRecord[];
  isLoading?: boolean;
  error?: string | null;
  emptyLabel: string;
  toolbar?: ReactNode;
  composer?: ReactNode;
  variant?: "edition" | "insight";
  onOpenThread: (threadId: string) => void;
}) {
  return (
    <div className="news-desk-forum-layout" data-news-desk-forum>
      {toolbar ?? null}
      {composer ?? null}
      <div className="news-desk-forum-index">
        <table className="news-desk-forum-index__table">
          <thead>
            <tr>
              <th>Topic</th>
              <th>{variant === "insight" ? "Domain" : "Scope"}</th>
              <th>Replies</th>
              <th>Last Post</th>
            </tr>
          </thead>
          <tbody>
            {threads.length ? threads.map((thread) => {
              const activeMessages = getActiveForumMessages(thread);
              const sortedMessages = [...activeMessages].sort(
                (left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0),
              );
              const lastMessage = sortedMessages.at(-1) ?? null;
              const replies = Math.max(activeMessages.length - 1, 0);
              const scopeLabel = thread.scope === "insight"
                ? (thread.sectionKey ?? thread.summary ?? "Insight")
                : thread.scope === "edition"
                  ? "Edition"
                  : `Section: ${normalizeForumThreadSectionLabel(thread, sections)}`;
              return (
                <tr key={thread.id}>
                  <td>
                    <button
                      className="news-desk-forum-index__topic"
                      type="button"
                      onClick={() => onOpenThread(thread.id)}
                    >
                      <strong>{thread.title}</strong>
                      {thread.summary ? <span>{thread.summary}</span> : null}
                    </button>
                  </td>
                  <td>{scopeLabel}</td>
                  <td>{replies}</td>
                  <td>
                    <div className="news-desk-forum-index__last-post">
                      <span>{formatDateTime(lastMessage?.createdAt ?? thread.lastMessageAt ?? thread.updatedAt ?? thread.createdAt)}</span>
                      <span>{lastMessage?.authorLabel ?? lastMessage?.role ?? "author"}</span>
                    </div>
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={4}>
                  {isLoading ? "Loading forum threads..." : emptyLabel}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {error ? <div className="category-steering-alert" data-tone="error">{error}</div> : null}
    </div>
  );
}

function ForumThreadComposer({
  draft,
  sections,
  error,
  onChange,
  onCancel,
  onSubmit,
}: {
  draft: ForumNewThreadDraft;
  sections: NewsroomSectionRecord[];
  error?: string | null;
  onChange: (next: ForumNewThreadDraft) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="news-desk-forum-compose news-desk-forum-compose--new-thread">
      <label>
        <span>Title</span>
        <input
          value={draft.title}
          onChange={(event) => onChange({ ...draft, title: event.target.value })}
          placeholder="Thread title"
        />
      </label>
      <label>
        <span>Scope</span>
        <select
          value={draft.scope}
          onChange={(event) => onChange({ ...draft, scope: event.target.value === "section" ? "section" : "edition" })}
        >
          <option value="edition">Edition</option>
          <option value="section">Section</option>
        </select>
      </label>
      {draft.scope === "section" ? (
        <label>
          <span>Section</span>
          <select
            value={draft.sectionId}
            onChange={(event) => onChange({ ...draft, sectionId: event.target.value })}
          >
            {sections.map((section) => (
              <option key={section.id} value={section.id}>{section.title}</option>
            ))}
          </select>
        </label>
      ) : null}
      <label>
        <span>Body</span>
        <textarea
          rows={6}
          value={draft.content}
          onChange={(event) => onChange({ ...draft, content: event.target.value })}
          placeholder="Write the opening post."
        />
      </label>
      {error ? <div className="category-steering-alert" data-tone="error">{error}</div> : null}
      <div className="news-desk-forum-compose__actions">
        <button type="button" onClick={onSubmit}>Post Thread</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function ForumThreadView({
  thread,
  sections,
  replyParentId,
  composeSummary,
  composeContent,
  composeError,
  deletingMessageId,
  focusMessageId = null,
  isDemo = false,
  variant = "edition",
  onBack,
  onReplyTarget,
  onDeleteMessage,
  onClearReplyTarget,
  onSummaryChange,
  onContentChange,
  onSubmit,
}: {
  thread: ForumThreadWithMessages;
  sections: NewsroomSectionRecord[];
  replyParentId: string;
  composeSummary: string;
  composeContent: string;
  composeError?: string | null;
  deletingMessageId?: string;
  focusMessageId?: string | null;
  isDemo?: boolean;
  variant?: "edition" | "insight";
  onBack: () => void;
  onReplyTarget: (messageId: string) => void;
  onDeleteMessage: (messageId: string) => void;
  onClearReplyTarget: () => void;
  onSummaryChange: (value: string) => void;
  onContentChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const messages = [...getActiveForumMessages(thread)].sort(
    (left, right) => Number(left.sequenceNumber ?? 0) - Number(right.sequenceNumber ?? 0),
  );
  const visibleCount = messages.length;
  const threadShareUrl = variant === "insight"
    ? buildInsightThreadUrl(thread.id, { demo: isDemo })
    : buildForumThreadUrl(thread.id, { demo: isDemo });

  useEffect(() => {
    if (!focusMessageId || typeof window === "undefined") return;
    const anchorId = getForumMessageAnchorId(focusMessageId);
    const target = document.getElementById(anchorId);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  }, [focusMessageId, messages.length, thread.id]);

  const copyShareLink = async (url: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      return;
    }
    if (typeof window === "undefined") return;
    window.prompt("Copy this forum link:", url);
  };

  return (
    <section className="category-steering-section news-desk-forum-thread-detail" aria-label="Forum thread detail">
      <header className="news-desk-overview-forum__thread-header">
        <div>
          <button className="news-desk-forum-thread-detail__back" type="button" onClick={onBack}>
            Back to Threads
          </button>
          <p className="story-label">
            {thread.scope === "insight"
              ? `Insight · ${thread.sectionKey ?? "discussion"}`
              : thread.scope === "edition"
                ? "Edition Thread"
                : `Section Thread: ${normalizeForumThreadSectionLabel(thread, sections)}`}
          </p>
          <h3>{thread.title}</h3>
        </div>
        <div className="news-desk-chip-row">
          <span>{visibleCount} messages</span>
          <span>Last activity {formatDateTime(thread.lastMessageAt ?? thread.updatedAt ?? thread.createdAt)}</span>
          <button
            type="button"
            onClick={() => {
              void copyShareLink(threadShareUrl);
            }}
          >
            Copy thread link
          </button>
        </div>
      </header>
      <div className="news-desk-forum-thread-messages">
        {messages.length ? messages.map((message) => (
          <article
            className="news-desk-forum-thread-message"
            id={getForumMessageAnchorId(message.id)}
            key={message.id}
          >
            <header>
              <strong>{message.authorLabel ?? message.role ?? "author"}</strong>
              <span>{formatDateTime(message.createdAt)}</span>
              <DropdownMenu>
                <DropdownMenuTrigger
                  aria-label={`Thread message actions for ${message.summary ?? message.id}`}
                  className="news-desk-forum-thread-message__menu"
                >
                  <MoreHorizontalIcon />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onReplyTarget(message.id)}>
                    Reply
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => {
                      const url = variant === "insight"
                        ? buildInsightThreadUrl(thread.id, { messageId: message.id, demo: isDemo })
                        : buildForumThreadUrl(thread.id, { messageId: message.id, demo: isDemo });
                      void copyShareLink(url);
                    }}
                  >
                    Copy message link
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    disabled={deletingMessageId === message.id}
                    onSelect={() => onDeleteMessage(message.id)}
                  >
                    {deletingMessageId === message.id ? "Deleting..." : "Delete"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </header>
            <h4>{message.summary ?? "Message"}</h4>
            <MarkdownContext className="news-desk-forum-thread-message__markdown" text={message.content ?? ""} />
          </article>
        )) : <EmptyRow label="No messages in this thread yet." />}
      </div>
      <div className="news-desk-forum-compose">
        <label>
          <span>Summary (optional)</span>
          <input
            value={composeSummary}
            onChange={(event) => onSummaryChange(event.target.value)}
            placeholder="Short summary"
          />
        </label>
        <label>
          <span>Reply</span>
          <textarea
            rows={5}
            value={composeContent}
            onChange={(event) => onContentChange(event.target.value)}
            placeholder="Write your reply."
          />
        </label>
        {replyParentId ? <p className="story-label">Replying to: {replyParentId}</p> : null}
        {composeError ? <div className="category-steering-alert" data-tone="error">{composeError}</div> : null}
        <div className="news-desk-forum-compose__actions">
          <button type="button" onClick={onSubmit}>Post Reply</button>
          {replyParentId ? <button type="button" onClick={onClearReplyTarget}>Clear reply target</button> : null}
        </div>
      </div>
    </section>
  );
}

function getActiveForumMessages(thread: ForumThreadWithMessages): MessageRecord[] {
  return (thread.messages ?? []).filter((message) => String(message.status || "active") === "active");
}

function normalizeEditionIdFromAssignment(
  assignment: AssignmentRecord,
  metadata: Record<string, unknown> | null,
): string | null {
  const direct = normalizeMetadataString(metadata?.editionId);
  if (direct) return direct;
  const slotTarget = metadataRecord(metadata?.slotTarget);
  const fromSlot = normalizeMetadataString(slotTarget?.editionId) ?? normalizeMetadataString(slotTarget?.edition_id);
  if (fromSlot) return fromSlot;
  const queue = String(assignment.queueKey ?? "");
  const match = queue.match(/edition:([^:]+)/);
  return match?.[1] ?? null;
}

function normalizeForumThreadSectionKey(thread: ForumThreadWithMessages): string | null {
  const metadata = metadataRecord(thread.metadata);
  return normalizeMetadataString(metadata?.sectionKey)
    ?? normalizeMetadataString(metadata?.sectionId)
    ?? normalizeMetadataString(thread.primaryAnchorId)
    ?? null;
}

function normalizeForumThreadSectionLabel(
  thread: ForumThreadWithMessages,
  sections: NewsroomSectionRecord[],
): string {
  const sectionKey = normalizeForumThreadSectionKey(thread);
  if (!sectionKey) return "Unknown section";
  return sections.find((section) => section.id === sectionKey)?.title ?? sectionKey;
}

function ReferenceLedger({ references, selectedLineageId }: { references: ReferenceRecord[]; selectedLineageId?: string | null }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(0);
  const normalizedQuery = query.trim().toLowerCase();
  const sortedReferences = useMemo(() => sortReferencesByRecency(references), [references]);
  const filteredReferences = useMemo(() => (
    sortedReferences
      .filter((reference) => !statusFilter || (reference.curationStatus ?? "pending") === statusFilter)
      .filter((reference) => !normalizedQuery || referenceMatchesQuery(reference, normalizedQuery))
  ), [normalizedQuery, sortedReferences, statusFilter]);
  const pageCount = Math.max(1, Math.ceil(filteredReferences.length / REFERENCE_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleReferences = filteredReferences.slice(currentPage * REFERENCE_PAGE_SIZE, (currentPage + 1) * REFERENCE_PAGE_SIZE);

  useEffect(() => {
    setPage(0);
  }, [normalizedQuery, references, statusFilter]);

  return (
    <>
      <ReferenceListControls
        label={`${filteredReferences.length} of ${references.length} ${referenceLedgerLabel(statusFilter)}`}
        onNext={() => setPage((value) => Math.min(value + 1, pageCount - 1))}
        onPrevious={() => setPage((value) => Math.max(value - 1, 0))}
        onQueryChange={setQuery}
        onStatusChange={setStatusFilter}
        page={currentPage}
        pageCount={pageCount}
        query={query}
        status={statusFilter}
      />
      <div className="news-desk-object-list" data-news-desk-reference-ledger>
        {visibleReferences.length ? visibleReferences.map((reference) => {
          const lineageId = reference.lineageId ?? reference.id;
          return (
            <ReferenceRow
              active={selectedLineageId === lineageId}
              key={reference.id}
              reference={reference}
            />
          );
        }) : <EmptyRow label={references.length ? "No references match this search" : "No private references imported"} />}
      </div>
    </>
  );
}

function useNewsroomPagedRows<T>({
  initialItems,
  enabled,
  loadPage,
  resetKey,
}: {
  initialItems: T[];
  enabled: boolean;
  loadPage: (nextToken?: string | null) => Promise<NewsroomRecordPage<T>>;
  resetKey: string;
}): NewsroomPagedRows<T> & { loadMore: () => void } {
  const shouldShowInitialLoading = enabled && initialItems.length === 0;
  const [state, setState] = useState<NewsroomPagedRows<T>>({
    items: initialItems,
    nextToken: null,
    hasMore: false,
    isLoading: shouldShowInitialLoading,
    isLoadingMore: false,
    error: null,
  });
  const loadPageRef = useRef(loadPage);
  loadPageRef.current = loadPage;

  useEffect(() => {
    if (!enabled) {
      setState({
        items: initialItems,
        nextToken: null,
        hasMore: false,
        isLoading: false,
        isLoadingMore: false,
        error: null,
      });
      return;
    }
    let active = true;
    setState((current) => ({ ...current, items: [], nextToken: null, hasMore: false, isLoading: true, isLoadingMore: false, error: null }));
    void loadPageRef.current(null)
      .then((page) => {
        if (!active) return;
        setState({
          items: page.items,
          nextToken: page.nextToken ?? null,
          hasMore: page.hasMore,
          isLoading: false,
          isLoadingMore: false,
          error: null,
        });
      })
      .catch((error) => {
        if (!active) return;
        setState({
          items: [],
          nextToken: null,
          hasMore: false,
          isLoading: false,
          isLoadingMore: false,
          error: error instanceof Error ? error.message : "Feed load failed",
        });
      });
    return () => {
      active = false;
    };
  }, [enabled, initialItems, resetKey]);

  const loadMore = () => {
    if (!enabled || state.isLoading || state.isLoadingMore || !state.hasMore) return;
    const token = state.nextToken ?? null;
    setState((current) => ({ ...current, isLoadingMore: true, error: null }));
    void loadPageRef.current(token)
      .then((page) => {
        setState((current) => ({
          ...current,
          items: mergeNewsroomRows(current.items, page.items),
          nextToken: page.nextToken ?? null,
          hasMore: page.hasMore,
          isLoadingMore: false,
          error: null,
        }));
      })
      .catch((error) => {
        setState((current) => ({
          ...current,
          isLoadingMore: false,
          error: error instanceof Error ? error.message : "Feed load failed",
        }));
      });
  };

  return { ...state, loadMore };
}

function mergeNewsroomRows<T>(current: T[], next: T[]): T[] {
  const seen = new Set<string>();
  const merged: T[] = [];
  for (const item of [...current, ...next]) {
    const id = typeof (item as { id?: unknown }).id === "string" ? (item as { id: string }).id : JSON.stringify(item);
    if (seen.has(id)) continue;
    seen.add(id);
    merged.push(item);
  }
  return merged;
}

function clearNewsroomCardGridAnimation(root: ParentNode | null, { killTweens = true }: { killTweens?: boolean } = {}) {
  if (!root) return;
  const grids = [
    ...(root instanceof HTMLElement && root.matches("[data-newsroom-card-grid]") ? [root] : []),
    ...Array.from(root.querySelectorAll<HTMLElement>("[data-newsroom-card-grid]")),
  ];
  const cards = [
    ...(root instanceof HTMLElement && root.matches("[data-newsroom-card]") ? [root] : []),
    ...Array.from(root.querySelectorAll<HTMLElement>("[data-newsroom-card]")),
  ];
  if (cards.length) {
    if (killTweens) gsap.killTweensOf(cards);
    gsap.set(cards, { clearProps: "transform,position,left,top,width,height,zIndex" });
  }
  for (const grid of grids) {
    grid.removeAttribute("data-newsroom-card-grid-animating");
  }
}

function newsroomCardGridAnimationContext(grid: HTMLElement): { absolute: boolean; parentAnimating: boolean } {
  const shell = grid.closest<HTMLElement>("[data-newsroom-list-detail-shell]");
  const surface = grid.closest<HTMLElement>("[data-newsroom-card-grid-surface]");
  const scale = Number(shell?.getAttribute("data-newsroom-card-scale") ?? "1");
  const isScaledSplitSurface = Number.isFinite(scale) && scale > 0 && scale < 0.99;
  return {
    absolute: !isScaledSplitSurface,
    parentAnimating: surface ? gsap.isTweening(surface) : false,
  };
}

const NEWSROOM_SPLIT_TARGET_TEXT_SCALE = 3 / 4;

function resolveRhythmicSplitScale(targetScale: number, shell: HTMLElement): number {
  const boundedTargetScale = Number.isFinite(targetScale) ? Math.min(Math.max(targetScale, 0.0001), 1) : 1;
  if (boundedTargetScale >= 0.999) return 1;
  const rhythm = Number.parseFloat(getComputedStyle(shell).getPropertyValue("--paper-rhythm"));
  if (!Number.isFinite(rhythm) || rhythm <= 0) return boundedTargetScale;
  const scaledRhythm = rhythm * boundedTargetScale;
  const snappedScaledRhythm = Math.floor(scaledRhythm);
  if (snappedScaledRhythm <= 0) return boundedTargetScale;
  const snappedScale = snappedScaledRhythm / rhythm;
  return Math.min(boundedTargetScale, Math.max(snappedScale, 1 / rhythm));
}

function NewsroomListDetailShell({
  actions = [],
  animatedDetail = false,
  canExpandDetail = true,
  detail,
  detailOpen = false,
  lede,
  list,
  onCloseDetail,
  selectionScrollKey,
  sectionKey,
  utilityActions = [],
}: {
  actions?: NewsroomDetailAction[];
  animatedDetail?: boolean;
  canExpandDetail?: boolean;
  detail: ReactNode;
  detailOpen?: boolean;
  lede?: ReactNode;
  list: ReactNode;
  onCloseDetail?: () => void;
  selectionScrollKey?: string | null;
  sectionKey: "assignments" | "concepts" | "insights" | "messages" | "references" | "topics";
  utilityActions?: NewsroomDetailAction[];
}) {
  const [detailMode, setDetailMode] = useState<"split" | "full">("split");
  const [renderedDetailOpen, setRenderedDetailOpen] = useState(detailOpen && canExpandDetail);
  const [isActionMenuOpen, setIsActionMenuOpen] = useState(false);
  const actionMenuRef = useRef<HTMLDivElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const mainColumnRef = useRef<HTMLDivElement | null>(null);
  const railRef = useRef<HTMLElement | null>(null);
  const listViewportRef = useRef<HTMLDivElement | null>(null);
  const listSurfaceRef = useRef<HTMLDivElement | null>(null);
  const baselineListWidthRef = useRef(0);
  const selectionScrollInitializedRef = useRef(false);
  const previousSelectionScrollKeyRef = useRef<string | null>(null);
  const canToggleDetailMode = useMediaQuery("(min-width: 1158px)");
  const prefersReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const enabledActions = actions.filter((action) => !action.disabled);
  const hasActions = actions.length > 0;
  const hasUtilityActions = utilityActions.length > 0;
  const actionSignature = useMemo(
    () => actions.map((action) => `${action.key}:${action.disabled ? "1" : "0"}`).join("|"),
    [actions],
  );
  const requestedDetailOpen = detailOpen && canExpandDetail;
  const shouldAnimateDetail = animatedDetail && canToggleDetailMode && detailMode === "split" && canExpandDetail;
  const effectiveDetailOpen = shouldAnimateDetail ? renderedDetailOpen : requestedDetailOpen;
  const isWideSplitListPane = animatedDetail && canToggleDetailMode && detailMode === "split";

  useEffect(() => {
    if (!canExpandDetail && detailMode === "full") setDetailMode("split");
  }, [canExpandDetail, detailMode]);

  useLayoutEffect(() => {
    if (!shouldAnimateDetail) {
      setRenderedDetailOpen(requestedDetailOpen);
      return;
    }
    if (requestedDetailOpen) setRenderedDetailOpen(true);
  }, [requestedDetailOpen, shouldAnimateDetail]);

  useLayoutEffect(() => {
    const shell = shellRef.current;
    const viewport = listViewportRef.current;
    const surface = listSurfaceRef.current;
    const rail = railRef.current;
    if (!shell || !viewport || !surface || !rail) return;
    gsap.killTweensOf([surface, viewport, rail]);

    const clearAnimatedLayout = () => {
      gsap.killTweensOf([surface, viewport, rail]);
      surface.style.width = "";
      surface.style.transform = "";
      surface.style.transformOrigin = "";
      surface.style.willChange = "";
      viewport.style.height = "";
      rail.style.transform = "";
      rail.style.opacity = "";
      rail.style.visibility = "";
      shell.style.setProperty("--newsroom-card-scale", "1");
      shell.style.setProperty("--newsroom-card-text-scale", "1");
      shell.setAttribute("data-newsroom-card-scale", "1");
    };

    if (!shouldAnimateDetail) {
      clearAnimatedLayout();
      return;
    }

    if (!renderedDetailOpen) {
      const closedWidth = viewport.getBoundingClientRect().width;
      if (closedWidth > 0) baselineListWidthRef.current = closedWidth;
      clearAnimatedLayout();
      return;
    }

    const baselineWidth = baselineListWidthRef.current || shell.getBoundingClientRect().width || viewport.getBoundingClientRect().width;
    const viewportWidth = viewport.getBoundingClientRect().width;
    const targetScale = baselineWidth > 0 ? viewportWidth / baselineWidth : 1;
    const boundedScale = resolveRhythmicSplitScale(targetScale, shell);
    const textScale = boundedScale > 0
      ? Math.max(1, NEWSROOM_SPLIT_TARGET_TEXT_SCALE / boundedScale)
      : 1;
    shell.style.setProperty("--newsroom-card-scale", String(boundedScale));
    shell.style.setProperty("--newsroom-card-text-scale", String(textScale));
    const scaledHeight = Math.max(1, surface.scrollHeight * boundedScale);
    shell.setAttribute("data-newsroom-card-scale", boundedScale.toFixed(4));
    surface.style.width = `${baselineWidth}px`;
    surface.style.transformOrigin = "top left";
    surface.style.willChange = "transform";
    viewport.style.height = `${scaledHeight}px`;
    clearNewsroomCardGridAnimation(surface);

    if (requestedDetailOpen) {
      gsap.fromTo(
        surface,
        { scale: 1 },
        { scale: boundedScale, duration: 0.42, ease: "power3.out" },
      );
      gsap.fromTo(
        rail,
        { autoAlpha: 0, x: 42 },
        { autoAlpha: 1, duration: 0.42, ease: "power3.out", x: 0 },
      );
      return;
    }

    gsap.to(surface, {
      duration: 0.32,
      ease: "power2.inOut",
      onComplete: () => {
        clearAnimatedLayout();
        setRenderedDetailOpen(false);
      },
      scale: 1,
    });
    gsap.to(rail, {
      autoAlpha: 0,
      duration: 0.26,
      ease: "power2.inOut",
      x: 42,
    });
  }, [requestedDetailOpen, renderedDetailOpen, sectionKey, shouldAnimateDetail]);

  useLayoutEffect(() => {
    const shell = shellRef.current;
    const mainColumn = mainColumnRef.current;
    if (!shell || !mainColumn) return;
    if (!isWideSplitListPane) {
      shell.style.removeProperty("--newsroom-list-pane-max-height");
      return;
    }

    let frameId = 0;
    const updatePaneHeight = () => {
      const rhythm = Number.parseFloat(getComputedStyle(shell).getPropertyValue("--paper-rhythm"));
      const bottomBuffer = Number.isFinite(rhythm) && rhythm > 0 ? rhythm * 1.5 : 24;
      const top = mainColumn.getBoundingClientRect().top;
      const maxHeight = Math.max(1, Math.floor(window.innerHeight - top - bottomBuffer));
      shell.style.setProperty("--newsroom-list-pane-max-height", `${maxHeight}px`);
    };
    const schedulePaneHeightUpdate = () => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(updatePaneHeight);
    };
    schedulePaneHeightUpdate();
    window.addEventListener("resize", schedulePaneHeightUpdate);
    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", schedulePaneHeightUpdate);
    };
  }, [effectiveDetailOpen, isWideSplitListPane, sectionKey]);

  useEffect(() => {
    const mainColumn = mainColumnRef.current;
    if (!mainColumn) return;
    const currentSelectionScrollKey = selectionScrollKey ?? null;
    if (!selectionScrollInitializedRef.current) {
      selectionScrollInitializedRef.current = true;
      previousSelectionScrollKeyRef.current = currentSelectionScrollKey;
      return;
    }
    if (previousSelectionScrollKeyRef.current === currentSelectionScrollKey) return;
    previousSelectionScrollKeyRef.current = currentSelectionScrollKey;
    if (!currentSelectionScrollKey || !isWideSplitListPane) return;
    const selectedCard = Array.from(mainColumn.querySelectorAll<HTMLElement>("[data-newsroom-card-id]"))
      .find((card) => card.getAttribute("data-newsroom-card-id") === currentSelectionScrollKey);
    if (!selectedCard) {
      mainColumn.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : "smooth" });
      return;
    }
    const targetTopRect = mainColumn.getBoundingClientRect().top;
    const cardTopRect = selectedCard.getBoundingClientRect().top;
    const deltaTop = cardTopRect - targetTopRect;
    const maxScrollTop = Math.max(0, mainColumn.scrollHeight - mainColumn.clientHeight);
    const targetScrollTop = Math.min(maxScrollTop, Math.max(0, mainColumn.scrollTop + deltaTop));
    mainColumn.scrollTo({ top: targetScrollTop, behavior: prefersReducedMotion ? "auto" : "smooth" });
  }, [isWideSplitListPane, prefersReducedMotion, selectionScrollKey]);

  useEffect(() => {
    if (!isActionMenuOpen) return;
    function handlePointerDown(event: PointerEvent) {
      if (actionMenuRef.current?.contains(event.target as Node)) return;
      setIsActionMenuOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsActionMenuOpen(false);
    }
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isActionMenuOpen]);

  useEffect(() => {
    setIsActionMenuOpen((current) => (current ? false : current));
  }, [actionSignature]);

  const detailToolbarActions = (
    <div className="newsroom-list-detail-shell__detail-toolbar-trailing">
      {utilityActions.map((action) => (
        <button
          type="button"
          aria-label={action.ariaLabel ?? action.label}
          className="news-desk-detail-toolbar-button news-desk-detail-toolbar-button--utility"
          disabled={action.disabled}
          key={action.key}
          onClick={action.onSelect}
          title={action.label}
        >
          {action.icon ?? null}
          <span>{action.label}</span>
        </button>
      ))}
      {hasActions ? (
        <div className="newsroom-list-detail-shell__action-menu-wrap" ref={actionMenuRef}>
          <button
            type="button"
            aria-label="Item actions"
            aria-expanded={isActionMenuOpen}
            className="news-desk-detail-toggle news-desk-detail-toggle--actions"
            disabled={enabledActions.length === 0}
            onClick={() => setIsActionMenuOpen((current) => !current)}
          >
            <EllipsisIcon />
          </button>
          {isActionMenuOpen ? (
            <div className="newsroom-list-detail-shell__action-menu" role="menu">
              {actions.map((action) => (
                <button
                  type="button"
                  disabled={action.disabled}
                  key={action.key}
                  onClick={() => {
                    setIsActionMenuOpen(false);
                    action.onSelect();
                  }}
                  role="menuitem"
                >
                  {action.icon ? <span className="newsroom-list-detail-shell__action-menu-icon">{action.icon}</span> : null}
                  <span>{action.label}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {canToggleDetailMode && onCloseDetail && effectiveDetailOpen ? (
        <button
          type="button"
          aria-label="Close detail"
          className="news-desk-detail-toggle news-desk-detail-toggle--close"
          onClick={onCloseDetail}
          title="Close detail"
        >
          <CloseIcon />
        </button>
      ) : null}
    </div>
  );

  return (
    <div
      ref={shellRef}
      className="news-desk-columns newsroom-list-detail-shell"
      data-news-desk-section={sectionKey}
      data-news-desk-assignments={sectionKey === "assignments" ? true : undefined}
      data-newsroom-list-detail-shell
      data-animated-detail={animatedDetail ? "true" : undefined}
      data-detail-mode={detailMode}
      data-detail-open={effectiveDetailOpen ? "true" : "false"}
      data-newsroom-card-scale="1"
    >
      <div className="news-desk-main-column" data-newsroom-list-pane={animatedDetail ? "true" : undefined} ref={mainColumnRef}>
        {lede}
        <div
          className="newsroom-list-detail-shell__list-viewport"
          data-newsroom-card-grid-viewport={animatedDetail ? true : undefined}
          ref={listViewportRef}
        >
          <div
            className="newsroom-list-detail-shell__list-surface"
            data-newsroom-card-grid-surface={animatedDetail ? true : undefined}
            ref={listSurfaceRef}
          >
            {list}
          </div>
        </div>
      </div>
      <aside className="news-desk-rail-column" ref={railRef}>
        {effectiveDetailOpen && canExpandDetail && !canToggleDetailMode && (onCloseDetail || hasActions || hasUtilityActions) ? (
          <div className="newsroom-list-detail-shell__narrow-toolbar">
            {onCloseDetail ? (
              <button type="button" className="news-desk-detail-toolbar-button" onClick={onCloseDetail}>
                <ChevronLeftIcon />
                Back to list
              </button>
            ) : null}
            {detailToolbarActions}
          </div>
        ) : null}
        {canToggleDetailMode && canExpandDetail && (effectiveDetailOpen || hasUtilityActions || hasActions) ? (
          <div className="newsroom-list-detail-shell__detail-toolbar">
            <div className="newsroom-list-detail-shell__detail-toolbar-leading">
              {canToggleDetailMode ? (
                <button
                  type="button"
                  aria-label={detailMode === "full" ? "Back to split" : "Full width"}
                  aria-pressed={detailMode === "full"}
                  className="news-desk-detail-toolbar-button news-desk-detail-toggle--width"
                  onClick={() => setDetailMode((current) => (current === "full" ? "split" : "full"))}
                >
                  {detailMode === "full" ? <ArrowRightFromLineIcon /> : <ArrowLeftToLineIcon />}
                  <span>{detailMode === "full" ? "Split" : "Full"}</span>
                </button>
              ) : null}
            </div>
            {detailToolbarActions}
          </div>
        ) : null}
        {detail}
      </aside>
    </div>
  );
}

function ArrowLeftToLineIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="M3 19V5" />
      <path d="m13 6-6 6 6 6" />
      <path d="M7 12h14" />
    </svg>
  );
}

function ChevronLeftIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="m15 18-6-6 6-6" />
    </svg>
  );
}

function ArrowRightFromLineIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="M3 5v14" />
      <path d="M21 12H7" />
      <path d="m15 18 6-6-6-6" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="M6 6 18 18" />
      <path d="M18 6 6 18" />
    </svg>
  );
}

function EllipsisIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
      <circle cx="5" cy="12" r="1" />
    </svg>
  );
}

function ThumbsUpIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="M7 10v10" />
      <path d="M11 20h7.2a1.8 1.8 0 0 0 1.8-1.5l1-6.5a1.8 1.8 0 0 0-1.8-2H15V6.8A1.8 1.8 0 0 0 13.2 5L11 10Z" />
      <path d="M7 20H4V10h3" />
    </svg>
  );
}

function ThumbsDownIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="M7 14V4" />
      <path d="M11 4h7.2A1.8 1.8 0 0 1 20 5.5l1 6.5a1.8 1.8 0 0 1-1.8 2H15v3.2a1.8 1.8 0 0 1-1.8 1.8L11 14Z" />
      <path d="M7 4H4v10h3" />
    </svg>
  );
}

function StarIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill={filled ? "currentColor" : "none"}
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="m12 3.8 2.55 5.16 5.7.83-4.12 4.02.97 5.68L12 16.8 6.9 19.49l.97-5.68-4.12-4.02 5.7-.83Z" />
    </svg>
  );
}

function LibraryBigIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <rect width="8" height="18" x="3" y="3" rx="1" />
      <path d="M7 3v18" />
      <path d="M20.4 18.9c.2.5-.1 1.1-.6 1.3l-1.9.7c-.5.2-1.1-.1-1.3-.6L11.1 5.1c-.2-.5.1-1.1.6-1.3l1.9-.7c.5-.2 1.1.1 1.3.6Z" />
    </svg>
  );
}

function InsightIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-detail-toggle__icon"
      fill="none"
      height="24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="24"
    >
      <path d="M9 18h6" />
      <path d="M10 22h4" />
      <path d="M8.5 14.5A6 6 0 1 1 15.5 14.5c-.8.7-1.2 1.5-1.4 2.5h-4.2c-.2-1-.6-1.8-1.4-2.5Z" />
    </svg>
  );
}

function SearchMarkIcon() {
  return (
    <svg
      aria-hidden="true"
      className="news-desk-search-mark__icon"
      fill="none"
      height="18"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="18"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function NewsroomDataGrid({
  columns,
  emptyLabel,
  filterLabel,
  filterOptions,
  filterValue,
  metrics,
  metricValue,
  onFilterChange,
  onMetricChange,
  onSelect,
  rows,
  selectedId,
  footerLabel,
  hasMore = false,
  isLoadingMore = false,
  onLoadMore,
}: {
  columns: NewsroomDataGridColumn[];
  emptyLabel: string;
  filterLabel: string;
  filterOptions: Array<{ key: string; label: string; count?: number }>;
  filterValue: string;
  metrics: NewsroomDataGridMetric[];
  metricValue: string;
  onFilterChange: (value: string) => void;
  onMetricChange: (value: string) => void;
  onSelect: (id: string) => void;
  rows: NewsroomDataGridRow[];
  selectedId?: string | null;
  footerLabel?: string | null;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  onLoadMore?: () => void;
}) {
  const columnTemplate = `repeat(${columns.length}, minmax(0, 1fr))`;
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!onLoadMore || !hasMore || isLoadingMore) return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
    }, { rootMargin: "240px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isLoadingMore, onLoadMore]);
  return (
    <>
      <div className="news-desk-data-grid-filter" data-news-desk-data-grid-filter>
        <label>
          <span>{filterLabel}</span>
          <select value={filterValue} onChange={(event) => onFilterChange(event.target.value)}>
            {filterOptions.map((option) => (
              <option key={option.key || "all"} value={option.key}>
                {option.count === undefined ? option.label : `${option.label} (${option.count})`}
              </option>
            ))}
          </select>
        </label>
        <div className="news-desk-data-grid-filter__metrics">
          {metrics.map((metric) => (
            <button
              type="button"
              key={metric.key || "all"}
              data-active={metricValue === metric.key || undefined}
              onClick={() => onMetricChange(metric.key)}
            >
              {metric.count} {metric.label}
            </button>
          ))}
        </div>
      </div>
      <div className="news-desk-data-grid" data-news-desk-data-grid>
        <div className="news-desk-data-grid__head" style={{ gridTemplateColumns: columnTemplate }}>
          {columns.map((column) => <span key={column.key}>{column.label}</span>)}
        </div>
        {rows.length ? rows.map((row) => (
          <button
            type="button"
            className="news-desk-data-grid__row"
            data-active={selectedId === row.id || undefined}
            key={row.id}
            onClick={() => onSelect(row.id)}
            style={{ gridTemplateColumns: columnTemplate }}
          >
            {row.cells.map((cell, index) => (
              index === 0
                ? <strong key={`${row.id}-${columns[index]?.key ?? index}`}>{cell}</strong>
                : <span key={`${row.id}-${columns[index]?.key ?? index}`}>{cell}</span>
            ))}
          </button>
        )) : <EmptyRow label={emptyLabel} />}
        {onLoadMore ? (
          <div className="news-desk-data-grid__footer" ref={sentinelRef}>
            {isLoadingMore ? "Loading more..." : hasMore ? footerLabel ?? "Scroll for more" : footerLabel ?? "End of feed"}
          </div>
        ) : null}
      </div>
    </>
  );
}

function NewsroomCardGrid({
  cards,
  emptyLabel,
  filterLabel,
  filterOptions,
  filterValue,
  metrics,
  metricValue,
  sortLabel,
  sortOptions,
  sortValue,
  isLoading = false,
  onFilterChange,
  onMetricChange,
  onSortChange,
  onSelect,
  selectedId,
  footerLabel,
  hasMore = false,
  isLoadingMore = false,
  onLoadMore,
}: {
  cards: NewsroomCardRecord[];
  emptyLabel: string;
  filterLabel: string;
  filterOptions: Array<{ key: string; label: string; count?: number }>;
  filterValue: string;
  metrics: NewsroomDataGridMetric[];
  metricValue: string;
  sortLabel?: string;
  sortOptions?: Array<{ key: string; label: string }>;
  sortValue?: string;
  isLoading?: boolean;
  onFilterChange: (value: string) => void;
  onMetricChange: (value: string) => void;
  onSortChange?: (value: string) => void;
  onSelect: (id: string) => void;
  selectedId?: string | null;
  footerLabel?: string | null;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  onLoadMore?: () => void;
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const { cancelLayout, captureLayout, gridRef } = useNewsroomCardGridFlip({
    cards,
    filterValue,
    metricValue,
    sortValue,
    selectedId,
  });
  useEffect(() => {
    if (!onLoadMore || !hasMore || isLoadingMore) return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        captureLayout();
        onLoadMore();
      }
    }, { rootMargin: "240px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [captureLayout, hasMore, isLoadingMore, onLoadMore]);
  return (
    <div className="newsroom-card-grid-shell" data-newsroom-card-grid-shell>
      <div
        className={[
          "news-desk-data-grid-filter",
          "newsroom-card-grid-filter",
          filterOptions.length ? "" : "news-desk-data-grid-filter--metrics-only",
          sortOptions?.length && onSortChange ? "news-desk-data-grid-filter--with-sort" : "",
        ].filter(Boolean).join(" ")}
        data-news-desk-data-grid-filter
      >
        {filterOptions.length ? (
          <label>
            <span>{filterLabel}</span>
            <select value={filterValue} onChange={(event) => {
              captureLayout();
              onFilterChange(event.target.value);
            }}>
              {filterOptions.map((option) => (
                <option key={option.key || "all"} value={option.key}>
                  {option.count === undefined ? option.label : `${option.label} (${option.count})`}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {sortOptions?.length && onSortChange ? (
          <label>
            <span>{sortLabel ?? "Sort"}</span>
            <select value={sortValue ?? ""} onChange={(event) => {
              captureLayout();
              onSortChange(event.target.value);
            }}>
              {sortOptions.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="news-desk-data-grid-filter__metrics">
          {metrics.map((metric) => (
            <button
              type="button"
              key={metric.key || "all"}
              data-active={metricValue === metric.key || undefined}
              onClick={() => {
                captureLayout();
                onMetricChange(metric.key);
              }}
            >
              {metric.count} {metric.label}
            </button>
          ))}
        </div>
      </div>
      <div className="newsroom-card-grid" data-newsroom-card-grid ref={gridRef}>
        {cards.length ? cards.map((card) => {
          const span = card.span ?? "1x1";
          return (
            <button
              type="button"
              aria-label={card.ariaLabel}
              className={`newsroom-card newsroom-card--span-${span}`}
              data-active={selectedId === card.id || undefined}
              data-newsroom-card
              data-newsroom-card-id={card.id}
              data-newsroom-card-span={span}
              data-newsroom-card-template-role={card.templateRole ?? "standard"}
              key={card.id}
              onClick={() => {
                cancelLayout();
                onSelect(card.id);
              }}
              {...card.dataAttributes}
            >
              <NewsroomCardContents card={card} />
            </button>
          );
        }) : isLoading ? (
          <NewsroomCardGridSkeleton sectionKey="references" />
        ) : (
          <div className="newsroom-card-grid__empty">
            <EmptyRow label={emptyLabel} />
          </div>
        )}
      </div>
      {onLoadMore ? (
        <div className="news-desk-data-grid__footer newsroom-card-grid__footer" ref={sentinelRef}>
          {isLoading && !cards.length
            ? "Loading..."
            : (!cards.length && !hasMore && !isLoadingMore && !footerLabel)
              ? null
              : isLoadingMore ? "Loading more..." : hasMore ? footerLabel ?? "Scroll for more" : footerLabel ?? "End of feed"}
        </div>
      ) : null}
    </div>
  );
}

function NewsroomCardGridSkeleton({ sectionKey }: { sectionKey?: "references" | "messages" | "assignments" | "topics" | "concepts" }) {
  const skeletonCards: Array<{ id: string; span: NewsroomCardSpan }> = [
    { id: "s1", span: "2x1" },
    { id: "s2", span: "1x1" },
    { id: "s3", span: "1x1" },
    { id: "s4", span: "1x1" },
    { id: "s5", span: "1x1" },
    { id: "s6", span: "2x1" },
  ];
  return (
    <div className="newsroom-card-grid__skeleton" data-newsroom-card-grid-skeleton data-newsroom-card-grid-skeleton-section={sectionKey ?? "default"}>
      {skeletonCards.map((card) => (
        <article className={`newsroom-card newsroom-card--skeleton newsroom-card--span-${card.span}`} key={card.id} aria-hidden="true">
          <span className="newsroom-card__skeleton-line newsroom-card__skeleton-line--kicker" />
          <span className="newsroom-card__skeleton-line newsroom-card__skeleton-line--title" />
          <span className="newsroom-card__skeleton-line newsroom-card__skeleton-line--body" />
          <span className="newsroom-card__skeleton-line newsroom-card__skeleton-line--meta" />
        </article>
      ))}
    </div>
  );
}

function useNewsroomCardGridFlip({
  cards,
  filterValue,
  metricValue,
  sortValue,
  selectedId,
}: {
  cards: NewsroomCardRecord[];
  filterValue: string;
  metricValue: string;
  sortValue?: string;
  selectedId?: string | null;
}) {
  const gridRef = useRef<HTMLDivElement | null>(null);
  const pendingStateRef = useRef<ReturnType<typeof Flip.getState> | null>(null);
  const pendingFlipOptionsRef = useRef<{ absolute: boolean } | null>(null);
  const hasMountedRef = useRef(false);
  const prefersReducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const layoutSignature = useMemo(() => (
    [
      selectedId ?? "",
      filterValue,
      metricValue,
      sortValue ?? "",
      cards.length,
      ...cards.map((card) => `${card.id}:${card.span ?? "1x1"}`),
    ].join("|")
  ), [cards, filterValue, metricValue, selectedId, sortValue]);

  const captureLayout = useCallback(() => {
    if (prefersReducedMotion) return;
    const grid = gridRef.current;
    if (!grid) return;
    const context = newsroomCardGridAnimationContext(grid);
    if (context.parentAnimating) {
      pendingStateRef.current = null;
      pendingFlipOptionsRef.current = null;
      clearNewsroomCardGridAnimation(grid);
      return;
    }
    const targets = Array.from(grid.querySelectorAll<HTMLElement>("[data-newsroom-card]"));
    if (!targets.length) return;
    clearNewsroomCardGridAnimation(grid);
    pendingStateRef.current = Flip.getState(targets);
    pendingFlipOptionsRef.current = { absolute: context.absolute };
  }, [prefersReducedMotion]);

  const cancelLayout = useCallback(() => {
    pendingStateRef.current = null;
    pendingFlipOptionsRef.current = null;
    const grid = gridRef.current;
    if (!grid) return;
    clearNewsroomCardGridAnimation(grid);
  }, []);

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    const state = pendingStateRef.current;
    const flipOptions = pendingFlipOptionsRef.current ?? { absolute: true };
    pendingStateRef.current = null;
    pendingFlipOptionsRef.current = null;
    if (prefersReducedMotion || !state) {
      grid.removeAttribute("data-newsroom-card-grid-animating");
      return;
    }
    const targets = Array.from(grid.querySelectorAll<HTMLElement>("[data-newsroom-card]"));
    if (!targets.length) {
      grid.removeAttribute("data-newsroom-card-grid-animating");
      return;
    }
    gsap.killTweensOf(targets);
    grid.setAttribute("data-newsroom-card-grid-animating", "true");
    grid.setAttribute("data-newsroom-card-flip-mode", flipOptions.absolute ? "absolute" : "transform");
    Flip.from(state, {
      absolute: flipOptions.absolute,
      duration: 0.42,
      ease: "power3.out",
      nested: true,
      scale: !flipOptions.absolute,
      onComplete: () => {
        grid.removeAttribute("data-newsroom-card-grid-animating");
        grid.removeAttribute("data-newsroom-card-flip-mode");
        clearNewsroomCardGridAnimation(grid, { killTweens: false });
      },
      onInterrupt: () => {
        grid.removeAttribute("data-newsroom-card-grid-animating");
        grid.removeAttribute("data-newsroom-card-flip-mode");
        clearNewsroomCardGridAnimation(grid, { killTweens: false });
      },
    });
  }, [layoutSignature, prefersReducedMotion]);

  return { cancelLayout, captureLayout, gridRef };
}

function SemanticDetailPanel({
  disabled = false,
  graph,
  knowledgeQuery,
  onReferenceReview,
  selected,
}: {
  disabled?: boolean;
  graph: SemanticGraph;
  knowledgeQuery?: KnowledgeQueryControl;
  onReferenceReview?: (reference: ReferenceRecord, action: ReferenceCurationAction, note?: string, reasonCode?: ReferenceRejectionReasonCode | null) => void;
  selected: SemanticObjectSummary | null;
}) {
  const [referenceRejectionReasonCode, setReferenceRejectionReasonCode] = useState<ReferenceRejectionReasonCode>("out_of_scope");

  useEffect(() => {
    setReferenceRejectionReasonCode("out_of_scope");
  }, [selected?.lineageId]);

  if (!selected) {
    return (
      <section className="category-steering-section" aria-labelledby="semantic-detail-title">
        <SectionHeader title="Semantic Detail" detail="No object selected" />
        <EmptyRow label="Select a reference, topic, concept, item, or message" />
      </section>
    );
  }

  const messages = graph.messagesFor(selected.kind, selected.lineageId);
  const insights = graph.insightsFor(selected.kind, selected.lineageId);
  const attachments = selected.kind === "reference" ? graph.attachmentsForReference(selected.lineageId) : [];
  const neighborGroups = graph.neighbors(selected.kind, selected.lineageId);
  const selectedReference = selected.kind === "reference" ? selected.record as ReferenceRecord : null;
  const selectedConcept = selected.kind === "semanticNode" ? selected.record as SemanticNodeRecord : null;

  return (
    <section className="category-steering-section" aria-labelledby="semantic-detail-title" data-news-desk-semantic-detail={selected.lineageId}>
      <SectionHeader title="Semantic Detail" detail={`${selected.kind} / v${selected.versionNumber ?? "?"}`} />
      <article className="news-desk-semantic-detail">
        <header>
          <strong>{selected.label}</strong>
          <span>{selected.subtitle ?? selected.lineageId}</span>
        </header>
        {knowledgeQuery ? <KnowledgeQueryStatus error={knowledgeQuery.error} loading={knowledgeQuery.loading} /> : null}
        {knowledgeQuery?.result ? (
          <KnowledgeQueryResultBlock result={knowledgeQuery.result} onClear={knowledgeQuery.clear} />
        ) : (
          <>
            {attachments.length ? (
              <div className="news-desk-detail-block">
                <p className="story-label">Attachments</p>
                {attachments.map((attachment) => (
                  <div className="news-desk-detail-line" key={attachment.id}>
                    <span>{attachment.role}</span>
                    <strong>{attachment.storagePath ?? attachment.sourceUri ?? attachment.filename ?? "unmapped file"}</strong>
                  </div>
                ))}
              </div>
            ) : null}
            {selectedReference && onReferenceReview ? (
              <ReferenceCurationPanel
                attachments={attachments}
                disabled={disabled}
                onReasonCodeChange={setReferenceRejectionReasonCode}
                reasonCode={referenceRejectionReasonCode}
                reference={selectedReference}
              />
            ) : null}
            {selectedConcept ? (
              <div className="news-desk-detail-block">
                <p className="story-label">Authority</p>
                <div className="news-desk-detail-line">
                  <span>Authority</span>
                  <strong>
                    {selectedConcept.authorityRank != null
                      ? `#${selectedConcept.authorityRank}`
                      : "Unknown"}
                  </strong>
                </div>
                <div className="news-desk-detail-line">
                  <span>Mentioned by</span>
                  <strong>
                    {selectedConcept.acceptedReferenceMentionCount != null
                      ? `${selectedConcept.acceptedReferenceMentionCount} references`
                      : "Unknown"}
                  </strong>
                </div>
                <div className="news-desk-detail-line">
                  <span>Connected to</span>
                  <strong>
                    {selectedConcept.relationCount != null
                      ? `${selectedConcept.relationCount} relations`
                      : "Unknown"}
                  </strong>
                </div>
                {selectedConcept.distinctSourceKindCount != null ? (
                  <div className="news-desk-detail-line">
                    <span>Source kinds</span>
                    <strong>{selectedConcept.distinctSourceKindCount}</strong>
                  </div>
                ) : null}
              </div>
            ) : null}
            {insights.length ? (
              <InsightMessageBlock insights={insights} />
            ) : null}
            {messages.length ? (
              <div className="news-desk-detail-block">
                <p className="story-label">Messages</p>
                {messages.slice(0, 4).map((message) => (
                  <div className="news-desk-detail-line" key={message.id}>
                    <span>{message.messageKind}</span>
                    <strong>
                      {message.messageKind === "reference_curation"
                        ? "Canonical summary is stored on the linked reference metadata attachment."
                        : (message.summary ?? "Stored message payload")}
                    </strong>
                  </div>
                ))}
              </div>
            ) : null}
            <NeighborGroups groups={neighborGroups} />
          </>
        )}
      </article>
    </section>
  );
}

function useModelPayloads(
  ownerKind: string,
  ownerId: string | null | undefined,
  roles: string[] = [],
) {
  const rolesKey = roles.join("|");
  const [state, setState] = useState<{
    error: string | null;
    loading: boolean;
    payloads: HydratedModelPayload[];
  }>({ error: null, loading: false, payloads: [] });
  const subscriptionClient = useMemo(
    () => generateClient<Schema>({ authMode: USER_POOL_AUTH_MODE }),
    [],
  );

  useEffect(() => {
    if (!ownerId) {
      setState({ error: null, loading: false, payloads: [] });
      return;
    }

    let active = true;
    const roleSet = new Set(rolesKey ? rolesKey.split("|").filter(Boolean) : []);
    const attachmentModel = subscriptionClient.models.ModelAttachment as unknown as ModelAttachmentSubscriptionModel | undefined;
    let subscriptions: ReferenceSubscription[] = [];

    const runLoad = (showLoading: boolean) => {
      if (showLoading) setState((current) => ({ ...current, error: null, loading: true }));
      return loadModelPayloadsForOwner(ownerKind, ownerId, rolesKey ? rolesKey.split("|") : undefined)
        .then((payloads) => {
          if (active) setState({ error: null, loading: false, payloads });
        })
        .catch((error) => {
          if (active) {
            setState({
              error: error instanceof Error ? error.message : "Could not load attached payloads.",
              loading: false,
              payloads: [],
            });
          }
        });
    };

    void runLoad(true);

    const handleAttachmentEvent = (value: unknown) => {
      const attachment = normalizeModelAttachmentSubscriptionPayload(value);
      if (!attachment) return;
      if (attachment.ownerKind !== ownerKind) return;
      if (attachment.ownerId !== ownerId) return;
      if (roleSet.size > 0 && !roleSet.has(attachment.role)) return;
      void runLoad(false);
    };

    if (attachmentModel && typeof attachmentModel.onCreate === "function" && typeof attachmentModel.onUpdate === "function") {
      subscriptions = [
        attachmentModel.onCreate().subscribe({ next: handleAttachmentEvent }),
        attachmentModel.onUpdate().subscribe({ next: handleAttachmentEvent }),
      ];
      if (typeof attachmentModel.onDelete === "function") {
        subscriptions.push(attachmentModel.onDelete().subscribe({ next: handleAttachmentEvent }));
      }
    }

    return () => {
      active = false;
      for (const subscription of subscriptions) subscription.unsubscribe();
    };
  }, [ownerKind, ownerId, rolesKey, subscriptionClient]);

  return state;
}

function modelPayloadByRole(payloads: HydratedModelPayload[], role: string): HydratedModelPayload | null {
  const candidates = payloads.filter((payload) => payload.attachment.role === role);
  if (!candidates.length) return null;
  const activeCandidates = candidates.filter((payload) => payload.attachment.status !== "deleted");
  const ranked = (activeCandidates.length ? activeCandidates : candidates).slice().sort((left, right) => {
    const leftTs = Date.parse(left.attachment.updatedAt || left.attachment.createdAt || "");
    const rightTs = Date.parse(right.attachment.updatedAt || right.attachment.createdAt || "");
    const leftRank = Number.isFinite(leftTs) ? leftTs : 0;
    const rightRank = Number.isFinite(rightTs) ? rightTs : 0;
    if (leftRank !== rightRank) return rightRank - leftRank;
    return right.attachment.id.localeCompare(left.attachment.id);
  });
  return ranked[0] ?? null;
}

function latestReferenceAttachment(attachments: ReferenceAttachmentRecord[]): ReferenceAttachmentRecord | null {
  const candidates = attachments
    .slice()
    .sort((left, right) => {
      const leftTs = Date.parse(left.importedAt || "");
      const rightTs = Date.parse(right.importedAt || "");
      const leftRank = Number.isFinite(leftTs) ? leftTs : 0;
      const rightRank = Number.isFinite(rightTs) ? rightTs : 0;
      if (leftRank !== rightRank) return rightRank - leftRank;
      return right.id.localeCompare(left.id);
    });
  return candidates[0] ?? null;
}

function isFilteredExtractedTextAttachment(attachment: ReferenceAttachmentRecord): boolean {
  if (attachment.role !== "extracted_text") return false;
  const metadata = parseMetadataObject(attachment.metadata);
  const filterStatus = normalizeMetadataString(metadata?.filterStatus);
  return filterStatus === "filtered";
}

type ReferenceExtractedTextTab = "filtered" | "original";
type ReferenceCitationTab = "references" | "cited-by";

function useNewsroomKnowledgeContext(target: KnowledgeQueryTarget | null) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [semanticText, setSemanticText] = useState("");
  const [maxTokens, setMaxTokens] = useState("1600");
  const [state, setState] = useState<{
    error: string | null;
    loading: boolean;
    result: KnowledgeQueryResponse | null;
    targetKey: string | null;
  }>({ error: null, loading: false, result: null, targetKey: null });
  const targetKey = target ? knowledgeQueryTargetKey(target) : null;

  useEffect(() => {
    setDialogOpen(false);
    setSemanticText("");
    setState({ error: null, loading: false, result: null, targetKey });
  }, [targetKey]);

  const run = async () => {
    if (!target) return;
    const tokenBudget = Math.max(400, Math.min(20_000, Number.parseInt(maxTokens, 10) || 1600));
    const request = buildNewsroomKnowledgeQueryInput(target, semanticText, tokenBudget);
    setState((current) => ({ ...current, error: null, loading: true, targetKey }));
    try {
      const result = await runNewsroomKnowledgeQuery(request);
      const text = result.context?.text?.trim();
      if (!text) {
        throw new Error("knowledgeQuery returned no markdown context.");
      }
      setState({ error: null, loading: false, result, targetKey });
      setDialogOpen(false);
    } catch (error) {
      setState({ error: error instanceof Error ? error.message : "Knowledge query failed.", loading: false, result: null, targetKey });
    }
  };
  const stateMatchesTarget = state.targetKey === targetKey;

  return {
    action: {
      ariaLabel: "Research knowledge context",
      disabled: !target || state.loading,
      icon: <LibraryBigIcon />,
      key: "knowledge-search",
      label: state.loading ? "Researching" : "Research",
      onSelect: () => setDialogOpen(true),
    } satisfies NewsroomDetailAction,
    clear: () => setState({ error: null, loading: false, result: null, targetKey }),
    dialog: target ? (
      <KnowledgeQueryDialog
        disabled={state.loading}
        maxTokens={maxTokens}
        semanticText={semanticText}
        target={target}
        onClose={() => setDialogOpen(false)}
        onMaxTokensChange={setMaxTokens}
        onRun={run}
        onSemanticTextChange={setSemanticText}
        open={dialogOpen}
      />
    ) : null,
    error: stateMatchesTarget ? state.error : null,
    loading: stateMatchesTarget ? state.loading : false,
    result: stateMatchesTarget ? state.result : null,
  };
}

function useNewsroomInsightComposer(
  target: InsightTarget | null,
  disabled: boolean,
  onCreate: (target: InsightTarget, summary: string, body: string) => Promise<void>,
): InsightComposerControl {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const [body, setBody] = useState("");
  const [state, setState] = useState<{ error: string | null; loading: boolean; targetKey: string | null }>({
    error: null,
    loading: false,
    targetKey: null,
  });
  const targetKey = target ? insightTargetKey(target) : null;

  useEffect(() => {
    setDialogOpen(false);
    setSummary("");
    setBody("");
    setState({ error: null, loading: false, targetKey });
  }, [targetKey]);

  const run = async () => {
    if (!target || disabled || state.loading) return;
    const cleanSummary = summary.trim();
    const cleanBody = body.trim();
    if (!cleanSummary || !cleanBody) {
      setState({ error: "Insight summary and body are required.", loading: false, targetKey });
      return;
    }
    setState({ error: null, loading: true, targetKey });
    try {
      await onCreate(target, cleanSummary, cleanBody);
      setState({ error: null, loading: false, targetKey });
      setDialogOpen(false);
      setSummary("");
      setBody("");
    } catch (error) {
      setState({
        error: error instanceof Error ? error.message : "Could not save insight.",
        loading: false,
        targetKey,
      });
    }
  };
  const stateMatchesTarget = state.targetKey === targetKey;
  const loading = stateMatchesTarget ? state.loading : false;
  const error = stateMatchesTarget ? state.error : null;

  return {
    action: {
      ariaLabel: "Add insight",
      disabled: disabled || !target || loading,
      icon: <InsightIcon />,
      key: "add-insight",
      label: loading ? "Saving Insight" : "Add Insight",
      onSelect: () => setDialogOpen(true),
    } satisfies NewsroomDetailAction,
    dialog: target ? (
      <InsightComposerDialog
        body={body}
        disabled={disabled || loading}
        error={error}
        onBodyChange={setBody}
        onClose={() => setDialogOpen(false)}
        onRun={run}
        onSummaryChange={setSummary}
        open={dialogOpen}
        summary={summary}
        target={target}
      />
    ) : null,
    error,
    loading,
  };
}

function useNewsroomRouteSearch({
  activeTab,
  assignments,
  categorys,
  dashboard,
  disabled,
  initialRequest,
  messages,
  newsroomSections,
  references,
  semanticNodes,
}: {
  activeTab: NewsDeskTab;
  assignments: AssignmentRecord[];
  categorys: CategorySteeringCategory[];
  dashboard: CategorySteeringDashboard;
  disabled: boolean;
  initialRequest: NewsroomSearchRequest | null;
  messages: MessageRecord[];
  newsroomSections: NewsroomSectionRecord[];
  references: ReferenceRecord[];
  semanticNodes: SemanticNodeRecord[];
}): NewsroomRouteSearchControl {
  const router = useRouter();
  const session = useOptionalNewsDeskClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [semanticText, setSemanticText] = useState("");
  const [maxTokens, setMaxTokens] = useState("1600");
  const [target, setTarget] = useState<KnowledgeQueryTarget | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (activeTab !== "search") return;
    setTarget(resolveKnowledgeQueryTarget(initialRequest?.anchor ?? null, { assignments, categorys, messages, newsroomSections, references, semanticNodes }));
    setSemanticText(initialRequest?.semanticQuery ?? "");
    setMaxTokens(String(initialRequest?.maxTokens ?? 1600));
    setDialogOpen(false);
  }, [activeTab, assignments, categorys, initialRequest, messages, newsroomSections, references, semanticNodes]);

  const navigate = () => {
    if (disabled) return;
    const tokenBudget = Math.max(400, Math.min(20_000, Number.parseInt(maxTokens, 10) || 1600));
    const request: NewsroomSearchRequest = {
      anchor: target?.anchor ?? null,
      from: currentNewsroomOriginHref(initialRequest?.from ?? null),
      maxTokens: tokenBudget,
      semanticQuery: semanticText.trim(),
    };
    const href = buildNewsroomSearchHref(request, dashboard.isDemo);
    const requestKey = serializeNewsroomSearchRequest(request);
    const routeToSearch = () => {
      session?.beginSearchTransition({
        href,
        kind: "modal-to-serp",
        requestKey,
        submittedAt: Date.now(),
      });
      router.push(href);
      setDialogOpen(false);
    };

    if (!modalRef.current || !dialogRef.current) {
      routeToSearch();
      return;
    }

    gsap.killTweensOf([modalRef.current, dialogRef.current]);
    gsap.timeline({ onComplete: routeToSearch })
      .to(modalRef.current, {
        autoAlpha: 0,
        duration: 0.18,
        ease: "power2.out",
      }, 0)
      .to(dialogRef.current, {
        duration: 0.18,
        ease: "power2.out",
        scale: 0.98,
        y: -20,
      }, 0);
  };

  return {
    dialog: (
      <NewsroomSearchDialog
        disabled={disabled}
        dialogRef={dialogRef}
        maxTokens={maxTokens}
        modalRef={modalRef}
        semanticText={semanticText}
        target={target}
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onMaxTokensChange={setMaxTokens}
        onRun={navigate}
        onSemanticTextChange={setSemanticText}
      />
    ),
    open: () => {
      const defaultAnchor = resolveCurrentRouteAnchor(activeTab);
      setTarget(resolveKnowledgeQueryTarget(defaultAnchor, { assignments, categorys, messages, newsroomSections, references, semanticNodes }));
      setSemanticText("");
      setMaxTokens("1600");
      setDialogOpen(true);
    },
  };
}

function parseNewsroomSearchRequest(selection: NewsDeskSelection): NewsroomSearchRequest | null {
  const anchorKind = normalizeKnowledgeQueryAnchorKind(selection.searchAnchorKind);
  const anchorId = selection.searchAnchorId?.trim() || null;
  const anchorLineageId = selection.searchAnchorLineageId?.trim() || null;
  const semanticQuery = selection.searchQuery?.trim() ?? "";
  const maxTokens = clampKnowledgeQueryTokenBudget(selection.searchMaxTokens);
  const from = normalizeNewsroomFromHref(selection.searchFrom ?? null);
  const anchor = anchorKind && anchorId ? {
    kind: anchorKind,
    id: anchorId,
    lineageId: anchorLineageId,
  } satisfies KnowledgeQueryAnchor : null;
  if (!anchor && !semanticQuery) return null;
  return {
    anchor,
    from,
    maxTokens,
    semanticQuery,
  };
}

function knowledgeQueryTargetKey(target: KnowledgeQueryTarget): string {
  return `${target.anchor.kind}:${target.anchor.lineageId ?? target.anchor.id}`;
}

function NewsroomSearchDialog({
  disabled,
  dialogRef,
  maxTokens,
  modalRef,
  onClose,
  onMaxTokensChange,
  onRun,
  onSemanticTextChange,
  open,
  semanticText,
  target,
}: {
  disabled: boolean;
  dialogRef?: RefObject<HTMLDivElement | null>;
  maxTokens: string;
  modalRef?: RefObject<HTMLDivElement | null>;
  onClose: () => void;
  onMaxTokensChange: (value: string) => void;
  onRun: () => void;
  onSemanticTextChange: (value: string) => void;
  open: boolean;
  semanticText: string;
  target?: KnowledgeQueryTarget | null;
}) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      className="news-desk-modal"
      data-news-desk-knowledge-query-modal
      ref={modalRef}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !disabled) onClose();
      }}
    >
      <div
        className="news-desk-modal__dialog news-desk-modal__dialog--knowledge-query"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="newsroom-search-title"
      >
        <header className="news-desk-modal__header">
          <div>
            <p className="story-label">Search</p>
            <h3 id="newsroom-search-title">Search</h3>
            <span>semantic + ontology</span>
          </div>
          <button type="button" disabled={disabled} onClick={onClose}>Close</button>
        </header>
        <div className="news-desk-knowledge-query-form">
          {target ? (
            <label>
              <span>Context Target</span>
              <div className="news-desk-knowledge-query-target">
                <strong>{target.title}</strong>
                <small>{target.anchor.kind} / {target.anchor.lineageId ?? target.anchor.id}</small>
              </div>
            </label>
          ) : null}
          <label>
            <span>Semantic Query</span>
            <textarea
              disabled={disabled}
              rows={5}
              value={semanticText}
              onChange={(event) => onSemanticTextChange(event.target.value)}
            />
          </label>
          <label>
            <span>Token Budget</span>
            <input
              disabled={disabled}
              inputMode="numeric"
              min="400"
              max="20000"
              step="100"
              type="number"
              value={maxTokens}
              onChange={(event) => onMaxTokensChange(event.target.value)}
            />
          </label>
        </div>
        <footer className="news-desk-modal__actions">
          <button type="button" disabled={disabled} onClick={onClose}>Cancel</button>
          <button type="button" className="news-desk-assignment-create-button" disabled={disabled} onClick={onRun}>
            {disabled ? "Searching" : "Search"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function KnowledgeQueryDialog({
  disabled,
  maxTokens,
  onClose,
  onMaxTokensChange,
  onRun,
  onSemanticTextChange,
  open,
  semanticText,
  target,
}: {
  disabled: boolean;
  maxTokens: string;
  onClose: () => void;
  onMaxTokensChange: (value: string) => void;
  onRun: () => void;
  onSemanticTextChange: (value: string) => void;
  open: boolean;
  semanticText: string;
  target: KnowledgeQueryTarget;
}) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      className="news-desk-modal"
      data-news-desk-knowledge-query-modal
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !disabled) onClose();
      }}
    >
      <div className="news-desk-modal__dialog news-desk-modal__dialog--knowledge-query" role="dialog" aria-modal="true" aria-labelledby="knowledge-query-title">
        <header className="news-desk-modal__header">
          <div>
            <p className="story-label">Knowledge Query</p>
            <h3 id="knowledge-query-title">{target.title}</h3>
            <span>{target.anchor.kind} / {target.anchor.lineageId ?? target.anchor.id}</span>
          </div>
          <button type="button" disabled={disabled} onClick={onClose}>Close</button>
        </header>
        <div className="news-desk-knowledge-query-form">
          <label>
            <span>Semantic Focus</span>
            <textarea
              disabled={disabled}
              rows={5}
              value={semanticText}
              onChange={(event) => onSemanticTextChange(event.target.value)}
            />
          </label>
          <label>
            <span>Token Budget</span>
            <input
              disabled={disabled}
              inputMode="numeric"
              min="400"
              max="20000"
              step="100"
              type="number"
              value={maxTokens}
              onChange={(event) => onMaxTokensChange(event.target.value)}
            />
          </label>
        </div>
        <footer className="news-desk-modal__actions">
          <button type="button" disabled={disabled} onClick={onClose}>Cancel</button>
          <button type="button" className="news-desk-assignment-create-button" disabled={disabled} onClick={onRun}>
            {disabled ? "Searching" : "Run Query"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function InsightComposerDialog({
  body,
  disabled,
  error,
  onBodyChange,
  onClose,
  onRun,
  onSummaryChange,
  open,
  summary,
  target,
}: {
  body: string;
  disabled: boolean;
  error: string | null;
  onBodyChange: (value: string) => void;
  onClose: () => void;
  onRun: () => void;
  onSummaryChange: (value: string) => void;
  open: boolean;
  summary: string;
  target: InsightTarget;
}) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") onRun();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, onRun, open]);

  if (!open) return null;

  return (
    <div
      className="news-desk-modal"
      data-news-desk-insight-modal
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !disabled) onClose();
      }}
    >
      <div className="news-desk-modal__dialog news-desk-modal__dialog--knowledge-query" role="dialog" aria-modal="true" aria-labelledby="insight-composer-title">
        <header className="news-desk-modal__header">
          <div>
            <p className="story-label">Insight</p>
            <h3 id="insight-composer-title">{target.title}</h3>
            <span>{target.kind} / {target.lineageId}</span>
          </div>
          <button type="button" disabled={disabled} onClick={onClose}>Close</button>
        </header>
        <div className="news-desk-knowledge-query-form">
          <label>
            <span>Summary</span>
            <input
              disabled={disabled}
              value={summary}
              onChange={(event) => onSummaryChange(event.target.value)}
            />
          </label>
          <label>
            <span>Insight Body</span>
            <textarea
              disabled={disabled}
              rows={8}
              value={body}
              onChange={(event) => onBodyChange(event.target.value)}
            />
          </label>
          {error ? <div className="category-steering-alert" role="status">{error}</div> : null}
        </div>
        <footer className="news-desk-modal__actions">
          <button type="button" disabled={disabled} onClick={onClose}>Cancel</button>
          <button type="button" className="news-desk-assignment-create-button" disabled={disabled || !summary.trim() || !body.trim()} onClick={onRun}>
            {disabled ? "Saving" : "Save Insight"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function KnowledgeQueryStatus({ error, loading }: { error: string | null; loading: boolean }) {
  if (!loading && !error) return null;
  return (
    <div className="news-desk-knowledge-query-status" role="status" data-state={error ? "error" : "pending"}>
      {loading ? <span className="news-desk-knowledge-query-spinner" aria-hidden="true" /> : null}
      <strong>{error ?? "Searching knowledge context..."}</strong>
    </div>
  );
}

function KnowledgeQueryResultBlock({
  clearLabel = "Show Record",
  onClear,
  result,
}: {
  clearLabel?: string;
  onClear: () => void;
  result: KnowledgeQueryResponse;
}) {
  const markdown = result.context?.text?.trim() ?? "";
  const warnings = result.warnings ?? [];
  const totalTokens = result.context?.totalTokens;
  return (
    <div className="news-desk-knowledge-query-result" data-news-desk-knowledge-query-result>
      <header>
        <p className="story-label">Knowledge Context</p>
        <button type="button" onClick={onClear}>{clearLabel}</button>
      </header>
      <MarkdownContext text={markdown} />
      <footer>
        {typeof totalTokens === "number" ? <span>{totalTokens} tokens</span> : null}
        {warnings.length ? <span>{warnings.length} warnings</span> : null}
      </footer>
      {warnings.length ? (
        <details>
          <summary>Warnings</summary>
          <ul>
            {warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function SearchDeskView({
  assignments,
  categories,
  initialRequest,
  isDemo,
  messages,
  references,
  semanticNodes,
}: {
  assignments: AssignmentRecord[];
  categories: CategorySteeringCategory[];
  initialRequest: NewsroomSearchRequest | null;
  isDemo?: boolean;
  messages: MessageRecord[];
  references: ReferenceRecord[];
  semanticNodes: SemanticNodeRecord[];
}) {
  const router = useRouter();
  const session = useOptionalNewsDeskClient();
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const resultRef = useRef<HTMLDivElement | null>(null);
  const statusRef = useRef<HTMLDivElement | null>(null);
  const previousLoadingRef = useRef(false);
  const [semanticText, setSemanticText] = useState(initialRequest?.semanticQuery ?? "");
  const [maxTokens, setMaxTokens] = useState(String(initialRequest?.maxTokens ?? 1600));
  const [runNonce, setRunNonce] = useState(0);
  const [state, setState] = useState<{
    error: string | null;
    loading: boolean;
    requestKey: string | null;
    result: KnowledgeQueryResponse | null;
  }>({
    error: null,
    loading: false,
    requestKey: null,
    result: null,
  });
  const target = useMemo(
    () => resolveKnowledgeQueryTarget(initialRequest?.anchor ?? null, { assignments, categorys: categories, messages, references, semanticNodes }),
    [assignments, categories, initialRequest?.anchor, messages, references, semanticNodes],
  );
  const requestKey = useMemo(() => serializeNewsroomSearchRequest(initialRequest), [initialRequest]);
  const hasRequest = Boolean(initialRequest && (initialRequest.anchor || initialRequest.semanticQuery.trim()));
  const statusVisible = state.loading || Boolean(state.error);

  useEffect(() => {
    setSemanticText(initialRequest?.semanticQuery ?? "");
    setMaxTokens(String(initialRequest?.maxTokens ?? 1600));
    setRunNonce(0);
    if (!hasRequest) {
      setState({ error: null, loading: false, requestKey: null, result: null });
    }
  }, [hasRequest, initialRequest?.maxTokens, initialRequest?.semanticQuery, requestKey]);

  useEffect(() => {
    if (!hasRequest || !initialRequest || isDemo) return;
    let active = true;
    setState((current) => ({ ...current, error: null, loading: true, requestKey }));
    const request = buildNewsroomKnowledgeQueryInput(target, initialRequest.semanticQuery, initialRequest.maxTokens);
    void runNewsroomKnowledgeQuery(request)
      .then((result) => {
        if (!active) return;
        const text = result.context?.text?.trim();
        if (!text) throw new Error("knowledgeQuery returned no markdown context.");
        setState({ error: null, loading: false, requestKey, result });
      })
      .catch((error) => {
        if (!active) return;
        setState((current) => ({
          ...current,
          error: error instanceof Error ? error.message : "Knowledge query failed.",
          loading: false,
          requestKey,
        }));
      });
    return () => {
      active = false;
    };
  }, [hasRequest, initialRequest, isDemo, requestKey, runNonce, target]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const focusSearch = () => inputRef.current?.focus();
    window.addEventListener("papyrus:newsroom-search-focus", focusSearch as EventListener);
    return () => window.removeEventListener("papyrus:newsroom-search-focus", focusSearch as EventListener);
  }, []);

  useLayoutEffect(() => {
    if (!panelRef.current) return;
    const transition = session?.searchTransition;
    if (!transition || transition.kind !== "modal-to-serp" || transition.requestKey !== requestKey || !statusVisible) return;

    gsap.killTweensOf([panelRef.current, statusRef.current]);
    gsap.set(panelRef.current, { autoAlpha: 0, y: 18 });
    if (statusRef.current) gsap.set(statusRef.current, { autoAlpha: 0, y: 14 });

    const timeline = gsap.timeline({
      onComplete: () => {
        session?.clearSearchTransition();
      },
    });
    timeline.to(panelRef.current, {
      autoAlpha: 1,
      duration: 0.24,
      ease: "power3.out",
      y: 0,
    }, 0);
    if (statusRef.current) {
      timeline.to(statusRef.current, {
        autoAlpha: 1,
        duration: 0.24,
        ease: "power3.out",
        y: 0,
      }, 0.06);
    }
  }, [requestKey, session, statusVisible]);

  useLayoutEffect(() => {
    const hadLoading = previousLoadingRef.current;
    previousLoadingRef.current = state.loading;

    if (!statusRef.current) return;
    gsap.killTweensOf([resultRef.current, statusRef.current]);

    if (state.loading) {
      if (resultRef.current && state.result) {
        gsap.to(resultRef.current, {
          autoAlpha: 0.3,
          duration: 0.18,
          ease: "power2.out",
          y: 8,
        });
      }
      gsap.fromTo(
        statusRef.current,
        { autoAlpha: 0, y: 12 },
        { autoAlpha: 1, duration: 0.24, ease: "power3.out", y: 0 },
      );
      return;
    }

    if (hadLoading && resultRef.current && state.result) {
      const timeline = gsap.timeline();
      timeline.to(statusRef.current, {
        autoAlpha: 0,
        duration: 0.18,
        ease: "power2.inOut",
        y: -8,
      }, 0);
      timeline.to(resultRef.current, {
        autoAlpha: 1,
        duration: 0.24,
        ease: "power3.out",
        y: 0,
      }, 0.04);
    }
  }, [state.loading, state.result]);

  const run = () => {
    const nextRequest: NewsroomSearchRequest = {
      anchor: target?.anchor ?? initialRequest?.anchor ?? null,
      from: initialRequest?.from ?? null,
      maxTokens: clampKnowledgeQueryTokenBudget(maxTokens),
      semanticQuery: semanticText.trim(),
    };
    const href = buildNewsroomSearchHref(nextRequest, isDemo);
    if (typeof window !== "undefined" && `${window.location.pathname}${window.location.search}` === href) {
      setRunNonce((value) => value + 1);
      return;
    }
    router.replace(href);
  };

  const clear = () => {
    router.replace(buildNewsroomSearchHref({ anchor: null, from: initialRequest?.from ?? null, maxTokens: 1600, semanticQuery: "" }, isDemo));
  };

  return (
    <section className="news-desk-search-view" aria-labelledby="newsroom-search-view-title" ref={panelRef}>
      <section className="news-desk-lede news-desk-search-view__lede">
        <div>
          <h2 id="newsroom-search-view-title">Search</h2>
          <p>semantic + ontology</p>
        </div>
        {initialRequest?.from ? (
          <Link className="news-desk-search-view__backlink" href={initialRequest.from}>Back to origin</Link>
        ) : null}
      </section>
      <section className="category-steering-section category-steering-section--lead news-desk-search-view__panel">
        <form
          className="news-desk-knowledge-query-form news-desk-knowledge-query-form--serp"
          data-newsroom-search-form
          onSubmit={(event) => {
            event.preventDefault();
            run();
          }}
        >
          {target ? (
            <label>
              <span>Context Target</span>
              <div className="news-desk-knowledge-query-target">
                <strong>{target.title}</strong>
                <small>{target.anchor.kind} / {target.anchor.lineageId ?? target.anchor.id}</small>
              </div>
            </label>
          ) : null}
          <label>
            <span>Semantic Query</span>
            <textarea
              id="newsroom-search-query"
              ref={inputRef}
              rows={5}
              value={semanticText}
              onChange={(event) => setSemanticText(event.target.value)}
            />
          </label>
          <label>
            <span>Token Budget</span>
            <input
              inputMode="numeric"
              min="400"
              max="20000"
              step="100"
              type="number"
              value={maxTokens}
              onChange={(event) => setMaxTokens(event.target.value)}
            />
          </label>
          <footer className="news-desk-search-view__actions">
            <button type="submit" className="news-desk-assignment-create-button">Run Search</button>
          </footer>
        </form>
        <div className="news-desk-search-view__status" ref={statusRef}>
          {statusVisible ? <KnowledgeQueryStatus error={state.error} loading={state.loading} /> : null}
        </div>
        {!hasRequest ? (
          <div className="news-desk-search-view__blank">
            <p className="story-label">Search</p>
            <h3>Enter a semantic query, or launch search from a record detail page for anchored context.</h3>
          </div>
        ) : (
          <>
            {state.result ? (
              <div ref={resultRef}>
                <KnowledgeQueryResultBlock clearLabel="Clear Search" onClear={clear} result={state.result} />
              </div>
            ) : null}
          </>
        )}
      </section>
    </section>
  );
}

function MarkdownContext({ className, text }: { className?: string; text: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(normalizeMarkdownForRendering(text)), [text]);
  return (
    <div className={className ? `news-desk-markdown-context ${className}` : "news-desk-markdown-context"}>
      {blocks.map((block, index) => renderMarkdownBlock(block, index))}
    </div>
  );
}

type MarkdownBlock =
  | { type: "code"; text: string }
  | { type: "heading"; depth: number; text: string }
  | { type: "list"; items: string[]; ordered: boolean }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "paragraph"; text: string };

function normalizeMarkdownForRendering(text: string): string {
  const trimmed = text.trim();
  const fencedMarkdown = /^```(?:markdown|md|mdx)?\s*\n([\s\S]*?)\n```$/i.exec(trimmed);
  const unwrapped = fencedMarkdown ? (fencedMarkdown[1] ?? "") : text;
  return normalizeMultilineMarkdownLinks(unwrapped);
}

function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = text.split(/\r?\n/);
  let paragraph: string[] = [];
  let list: string[] = [];
  let listOrdered = false;
  let code: string[] = [];
  let inCode = false;
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ").trim() });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      blocks.push({ type: "list", items: list, ordered: listOrdered });
      list = [];
      listOrdered = false;
    }
  };
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    if (line.trim().startsWith("```")) {
      if (inCode) {
        blocks.push({ type: "code", text: code.join("\n") });
        code = [];
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    if (
      lineIndex + 1 < lines.length
      && looksLikeMarkdownTableHeaderLine(line)
      && isMarkdownTableDividerLine(lines[lineIndex + 1] ?? "")
    ) {
      flushParagraph();
      flushList();
      const headerCells = splitMarkdownTableCells(line);
      const dividerCells = splitMarkdownTableCells(lines[lineIndex + 1] ?? "");
      const columnCount = Math.max(headerCells.length, dividerCells.length, 1);
      const headers = normalizeMarkdownTableCells(headerCells, columnCount);
      const rows: string[][] = [];
      lineIndex += 2;
      while (lineIndex < lines.length) {
        const rowLine = lines[lineIndex] ?? "";
        if (!looksLikeMarkdownTableRowLine(rowLine)) {
          lineIndex -= 1;
          break;
        }
        rows.push(normalizeMarkdownTableCells(splitMarkdownTableCells(rowLine), columnCount));
        lineIndex += 1;
      }
      if (lineIndex >= lines.length) lineIndex -= 1;
      blocks.push({ type: "table", headers, rows });
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", depth: heading[1].length, text: heading[2].trim() });
      continue;
    }
    const bullet = /^(?:([-*+])\s+|(\d+)[.)]\s+)(.+)$/.exec(trimmed);
    if (bullet) {
      flushParagraph();
      const ordered = Boolean(bullet[2]);
      if (list.length && listOrdered !== ordered) flushList();
      listOrdered = ordered;
      list.push((bullet[3] ?? "").trim());
      continue;
    }
    flushList();
    paragraph.push(trimmed);
  }
  flushParagraph();
  flushList();
  if (code.length) blocks.push({ type: "code", text: code.join("\n") });
  return blocks;
}

function renderMarkdownBlock(block: MarkdownBlock, index: number): ReactNode {
  const key = `${block.type}-${index}`;
  if (block.type === "code") return <pre className="news-desk-analysis-command" key={key}>{block.text}</pre>;
  if (block.type === "list") {
    const ListTag = block.ordered ? "ol" : "ul";
    return (
      <ListTag key={key}>
        {block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>)}
      </ListTag>
    );
  }
  if (block.type === "heading") {
    if (block.depth <= 1) return <h3 key={key}>{block.text}</h3>;
    if (block.depth === 2) return <h4 key={key}>{block.text}</h4>;
    return <h5 key={key}>{block.text}</h5>;
  }
  if (block.type === "table") {
    return (
      <table key={key}>
        <thead>
          <tr>
            {block.headers.map((header, headerIndex) => (
              <th key={`${key}-head-${headerIndex}`} scope="col">{renderInlineMarkdown(header)}</th>
            ))}
          </tr>
        </thead>
        {block.rows.length ? (
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${key}-row-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${key}-row-${rowIndex}-cell-${cellIndex}`}>{renderInlineMarkdown(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        ) : null}
      </table>
    );
  }
  return <p key={key}>{renderInlineMarkdown(block.text)}</p>;
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let index = 0;
  let plain = "";
  const flushPlain = () => {
    if (!plain) return;
    nodes.push(plain);
    plain = "";
  };

  while (index < text.length) {
    const linkLike = parseMarkdownLinkLikeAt(text, index);
    if (linkLike) {
      flushPlain();
      if (!linkLike.image) {
        const href = normalizeInlineMarkdownHref(linkLike.hrefRaw);
        const label = collapseMarkdownLinkLabel(linkLike.label);
        if (href) {
          nodes.push(
            <a href={href} key={`${index}-link`} rel="noopener noreferrer" target="_blank">
              {renderInlineMarkdown(label)}
            </a>,
          );
        } else {
          nodes.push(linkLike.raw);
        }
      }
      index += linkLike.length;
      continue;
    }

    if (text.startsWith("**", index) || text.startsWith("__", index)) {
      const marker = text.slice(index, index + 2);
      const end = text.indexOf(marker, index + 2);
      if (end > index + 2) {
        flushPlain();
        nodes.push(<strong key={`${index}-strong`}>{renderInlineMarkdown(text.slice(index + 2, end))}</strong>);
        index = end + 2;
        continue;
      }
    }

    if (text.startsWith("~~", index)) {
      const end = text.indexOf("~~", index + 2);
      if (end > index + 2) {
        flushPlain();
        nodes.push(<del key={`${index}-strike`}>{renderInlineMarkdown(text.slice(index + 2, end))}</del>);
        index = end + 2;
        continue;
      }
    }

    if (text[index] === "*" || text[index] === "_") {
      const marker = text[index];
      const end = text.indexOf(marker, index + 1);
      if (end > index + 1) {
        flushPlain();
        nodes.push(<em key={`${index}-em`}>{renderInlineMarkdown(text.slice(index + 1, end))}</em>);
        index = end + 1;
        continue;
      }
    }

    if (text[index] === "`") {
      const end = text.indexOf("`", index + 1);
      if (end > index + 1) {
        flushPlain();
        nodes.push(<code key={`${index}-code`}>{text.slice(index + 1, end)}</code>);
        index = end + 1;
        continue;
      }
    }

    const autolinkMatch = /^(<https?:\/\/[^>\s]+>|https?:\/\/[^\s<]+)/.exec(text.slice(index));
    if (autolinkMatch) {
      flushPlain();
      const token = autolinkMatch[1];
      const href = normalizeInlineMarkdownHref(token);
      if (href) {
        nodes.push(
          <a href={href} key={`${index}-autolink`} rel="noopener noreferrer" target="_blank">
            {href}
          </a>,
        );
      } else {
        nodes.push(token);
      }
      index += token.length;
      continue;
    }

    plain += text[index];
    index += 1;
  }

  flushPlain();
  return nodes;
}

function normalizeInlineMarkdownHref(rawHref: string): string | null {
  const href = extractMarkdownHrefDestination(rawHref);
  if (!href) return null;
  if (/^(https?:\/\/|mailto:)/i.test(href)) return href;
  return null;
}

function normalizeMultilineMarkdownLinks(text: string): string {
  let normalized = "";
  let index = 0;
  while (index < text.length) {
    const linkLike = parseMarkdownLinkLikeAt(text, index);
    if (!linkLike || linkLike.image || !linkLike.raw.includes("\n")) {
      normalized += text[index];
      index += 1;
      continue;
    }
    const href = extractMarkdownHrefDestination(linkLike.hrefRaw);
    const label = collapseMarkdownLinkLabel(linkLike.label);
    if (!href || !label) {
      normalized += linkLike.raw;
      index += linkLike.length;
      continue;
    }
    normalized += `[${label}](${href})`;
    index += linkLike.length;
  }
  return normalized;
}

function collapseMarkdownLinkLabel(label: string): string {
  const withoutImages = label.replace(/!\[[^\]]*\]\((?:[^)(]|\([^)(]*\))*\)/g, " ");
  return withoutImages
    .replace(/\r?\n+/g, " ")
    .replace(/(^|\s)#{1,6}\s+/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function extractMarkdownHrefDestination(rawHref: string): string {
  const trimmed = rawHref.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("<")) {
    const closing = trimmed.indexOf(">");
    if (closing > 1) return trimmed.slice(1, closing).trim();
  }
  const match = /^(\S+)/.exec(trimmed);
  return match?.[1]?.trim() ?? "";
}

function parseMarkdownLinkLikeAt(
  source: string,
  startIndex: number,
): { hrefRaw: string; image: boolean; label: string; length: number; raw: string } | null {
  const image = source.startsWith("![", startIndex);
  const link = source[startIndex] === "[";
  if (!image && !link) return null;
  const labelStart = startIndex + (image ? 2 : 1);
  const labelEnd = findMatchingBracketIndex(source, labelStart, "[", "]");
  if (labelEnd < 0) return null;
  let next = labelEnd + 1;
  while (next < source.length && /\s/.test(source[next])) next += 1;
  if (source[next] !== "(") return null;
  const hrefStart = next + 1;
  const hrefEnd = findMatchingBracketIndex(source, hrefStart, "(", ")");
  if (hrefEnd < 0) return null;
  const raw = source.slice(startIndex, hrefEnd + 1);
  return {
    image,
    label: source.slice(labelStart, labelEnd),
    hrefRaw: source.slice(hrefStart, hrefEnd),
    length: raw.length,
    raw,
  };
}

function findMatchingBracketIndex(source: string, contentStart: number, open: string, close: string): number {
  let depth = 1;
  for (let index = contentStart; index < source.length; index += 1) {
    const ch = source[index];
    if (ch === "\\") {
      index += 1;
      continue;
    }
    if (ch === open) {
      depth += 1;
      continue;
    }
    if (ch !== close) continue;
    depth -= 1;
    if (depth === 0) return index;
  }
  return -1;
}

function looksLikeMarkdownTableHeaderLine(line: string): boolean {
  return /\|/.test(line.trim());
}

function looksLikeMarkdownTableRowLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  if (!/\|/.test(trimmed)) return false;
  if (isMarkdownTableDividerLine(trimmed)) return false;
  return true;
}

function isMarkdownTableDividerLine(line: string): boolean {
  const cells = splitMarkdownTableCells(line);
  if (!cells.length) return false;
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitMarkdownTableCells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!trimmed) return [];
  const cells: string[] = [];
  let current = "";
  let escaping = false;
  for (let index = 0; index < trimmed.length; index += 1) {
    const ch = trimmed[index];
    if (escaping) {
      current += ch;
      escaping = false;
      continue;
    }
    if (ch === "\\") {
      escaping = true;
      current += ch;
      continue;
    }
    if (ch === "|") {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += ch;
  }
  cells.push(current.trim());
  return cells;
}

function normalizeMarkdownTableCells(cells: string[], columnCount: number): string[] {
  const normalized = cells.slice(0, columnCount);
  while (normalized.length < columnCount) normalized.push("");
  return normalized;
}

function PayloadDetailBlock({
  fallback,
  hideLabel = false,
  label,
  loading,
  payload,
  preferJson = false,
}: {
  fallback: string;
  hideLabel?: boolean;
  label: string;
  loading: boolean;
  payload: HydratedModelPayload | null;
  preferJson?: boolean;
}) {
  const content = preferJson && payload?.json !== null && payload?.json !== undefined
    ? JSON.stringify(payload.json, null, 2)
    : payload?.text;
  return (
    <div className="news-desk-detail-block">
      {hideLabel ? null : <p className="story-label">{label}</p>}
      {loading ? <p className="news-desk-detail-copy">Loading attached payload...</p> : null}
      {!loading && payload?.error ? <p className="news-desk-detail-copy">{payload.error}</p> : null}
      {!loading && !payload?.error && content ? <pre className="news-desk-analysis-command">{content}</pre> : null}
      {!loading && !payload && <p className="news-desk-detail-copy">{fallback}</p>}
      {!loading && payload && !payload.error && !content ? <p className="news-desk-detail-copy">{fallback}</p> : null}
    </div>
  );
}

function InsightMessageBlock({ insights }: { insights: MessageRecord[] }) {
  return (
    <div className="news-desk-detail-block">
      <p className="story-label">Insights</p>
      {insights.slice(0, 6).map((message) => (
        <div className="news-desk-detail-line" key={message.id}>
          <span>{message.authorLabel ?? "knowledge"}</span>
          <strong>{message.summary ?? "Stored insight"}</strong>
        </div>
      ))}
    </div>
  );
}

function ReferenceDetailPanel({
  categories,
  categorySets,
  corpora,
  curation,
  disabled,
  graph,
  onCreateInsight,
  onMoveCorpus,
  onReview,
  onReviewTopicLabel,
  onSetQualityRating,
  qualityActionState,
  reference,
  curationRunStatus,
  curationMenuActions,
  knowledgeQuery,
  semanticRelations,
}: {
  categories: CategorySteeringCategory[];
  categorySets: CategorySteeringCategorySet[];
  corpora: CategorySteeringCorpus[];
  curation: ReferenceCurationDisplayState | null;
  disabled: boolean;
  graph: SemanticGraph;
  onCreateInsight: (target: InsightTarget, summary: string, body: string) => Promise<void>;
  onMoveCorpus: (reference: ReferenceRecord, corpusId: string) => void;
  onReview: (action: ReferenceCurationAction) => void;
  onReviewTopicLabel: (input: { action: TopicLabelAction; category: CategorySteeringCategory; note?: string | null; reference: ReferenceRecord; sourceRelationId?: string | null }) => void;
  onSetQualityRating: (reference: ReferenceRecord, rating: number) => void;
  qualityActionState: ReferenceQualityActionState | null;
  reference: ReferenceRecord | null;
  curationRunStatus: ReferenceCurationRunStatus | null;
  curationMenuActions: NewsroomDetailAction[];
  knowledgeQuery: KnowledgeQueryControl;
  semanticRelations: SemanticRelationRecord[];
}) {
  const referencePayloadState = useModelPayloads("reference", reference?.id, ["metadata"]);
  const referenceLineageId = reference?.lineageId ?? reference?.id ?? "";
  const graphAttachments = useMemo(
    () => (reference ? graph.attachmentsForReference(referenceLineageId) : []),
    [graph, reference, referenceLineageId],
  );
  const [attachments, setAttachments] = useState<ReferenceAttachmentRecord[]>(graphAttachments);

  useEffect(() => {
    setAttachments(graphAttachments);
  }, [graphAttachments]);

  useEffect(() => {
    if (!referenceLineageId) {
      setAttachments([]);
      return;
    }
    let active = true;
    void loadReferenceAttachmentsForLineageId(referenceLineageId)
      .then((loadedAttachments) => {
        if (!active || !loadedAttachments.length) return;
        const merged = new Map<string, ReferenceAttachmentRecord>();
        for (const attachment of [...graphAttachments, ...loadedAttachments]) {
          merged.set(attachment.id, attachment);
        }
        setAttachments(Array.from(merged.values()).sort((left, right) => left.sortKey.localeCompare(right.sortKey)));
      })
      .catch(() => {
        if (!active) return;
        setAttachments(graphAttachments);
      });
    return () => {
      active = false;
    };
  }, [graphAttachments, referenceLineageId]);

  const extractedTextAttachments = useMemo(
    () => attachments.filter((attachment) => attachment.role === "extracted_text"),
    [attachments],
  );
  const extractedTextRawAttachments = useMemo(
    () => attachments.filter((attachment) => attachment.role === "extracted_text_raw"),
    [attachments],
  );
  const extractedTextFilteredAttachment = useMemo(
    () => latestReferenceAttachment(extractedTextAttachments.filter(isFilteredExtractedTextAttachment)),
    [extractedTextAttachments],
  );
  const extractedTextOriginalAttachment = useMemo(
    () => latestReferenceAttachment(extractedTextRawAttachments)
      ?? latestReferenceAttachment(extractedTextAttachments.filter((attachment) => !isFilteredExtractedTextAttachment(attachment))),
    [extractedTextRawAttachments, extractedTextAttachments],
  );
  const [extractedTextFilteredState, setExtractedTextFilteredState] = useState<{
    error: string | null;
    loading: boolean;
    text: string | null;
  }>({ error: null, loading: false, text: null });
  const [extractedTextOriginalState, setExtractedTextOriginalState] = useState<{
    error: string | null;
    loading: boolean;
    text: string | null;
  }>({ error: null, loading: false, text: null });
  const [activeExtractedTextTab, setActiveExtractedTextTab] = useState<ReferenceExtractedTextTab>("filtered");
  const [activeCitationTab, setActiveCitationTab] = useState<ReferenceCitationTab>("references");
  const [attachmentLinksById, setAttachmentLinksById] = useState<Record<string, string>>({});
  const [citationState, setCitationState] = useState<{
    error: string | null;
    incoming: SemanticRelationRecord[];
    loaded: boolean;
    loading: boolean;
    outgoing: SemanticRelationRecord[];
  }>({
    error: null,
    incoming: [],
    loaded: false,
    loading: false,
    outgoing: [],
  });

  useEffect(() => {
    const storagePath = extractedTextFilteredAttachment?.storagePath ?? null;
    if (!storagePath) {
      setExtractedTextFilteredState({ error: null, loading: false, text: null });
      return;
    }
    let active = true;
    setExtractedTextFilteredState({ error: null, loading: true, text: null });
    void loadStoragePathText(storagePath)
      .then((result) => {
        if (!active) return;
        setExtractedTextFilteredState({ error: result.error, loading: false, text: result.text });
      })
      .catch((error) => {
        if (!active) return;
        setExtractedTextFilteredState({
          error: error instanceof Error ? error.message : "Could not load filtered extracted text.",
          loading: false,
          text: null,
        });
      });
    return () => {
      active = false;
    };
  }, [extractedTextFilteredAttachment?.storagePath]);

  useEffect(() => {
    const storagePath = extractedTextOriginalAttachment?.storagePath ?? null;
    if (!storagePath) {
      setExtractedTextOriginalState({ error: null, loading: false, text: null });
      return;
    }
    let active = true;
    setExtractedTextOriginalState({ error: null, loading: true, text: null });
    void loadStoragePathText(storagePath)
      .then((result) => {
        if (!active) return;
        setExtractedTextOriginalState({ error: result.error, loading: false, text: result.text });
      })
      .catch((error) => {
        if (!active) return;
        setExtractedTextOriginalState({
          error: error instanceof Error ? error.message : "Could not load original extracted text.",
          loading: false,
          text: null,
        });
      });
    return () => {
      active = false;
    };
  }, [extractedTextOriginalAttachment?.storagePath]);

  useEffect(() => {
    if (!attachments.length) {
      setAttachmentLinksById({});
      return;
    }
    let active = true;
    const staticLinks = new Map<string, string>();
    const storageLookups: Array<{ id: string; storagePath: string }> = [];

    for (const attachment of attachments) {
      if (attachment.storagePath) {
        storageLookups.push({ id: attachment.id, storagePath: attachment.storagePath });
        continue;
      }
      const sourceHref = normalizeReferenceDetailHttpUri(attachment.sourceUri);
      if (sourceHref) {
        staticLinks.set(attachment.id, sourceHref);
      }
    }

    if (!storageLookups.length) {
      setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
      return;
    }

    setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
    void Promise.all(storageLookups.map(async (lookup) => {
      const result = await loadStoragePathUrl(lookup.storagePath);
      return { id: lookup.id, url: result.url };
    }))
      .then((resolved) => {
        if (!active) return;
        const merged = new Map(staticLinks);
        for (const entry of resolved) {
          if (entry.url) merged.set(entry.id, entry.url);
        }
        setAttachmentLinksById(Object.fromEntries(merged.entries()));
      })
      .catch(() => {
        if (!active) return;
        setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
      });

    return () => {
      active = false;
    };
  }, [attachments]);

  const extractedTextTabs = useMemo(() => {
    const tabs: Array<{ attachment: ReferenceAttachmentRecord; label: string; mode: ReferenceExtractedTextTab }> = [];
    if (extractedTextFilteredAttachment) {
      tabs.push({ mode: "filtered", label: "Filtered", attachment: extractedTextFilteredAttachment });
    }
    if (extractedTextOriginalAttachment) {
      tabs.push({ mode: "original", label: "Original", attachment: extractedTextOriginalAttachment });
    }
    return tabs;
  }, [extractedTextFilteredAttachment, extractedTextOriginalAttachment]);

  useEffect(() => {
    if (!extractedTextTabs.length) return;
    if (extractedTextTabs.some((tab) => tab.mode === activeExtractedTextTab)) return;
    setActiveExtractedTextTab(extractedTextTabs[0].mode);
  }, [activeExtractedTextTab, extractedTextTabs]);

  useEffect(() => {
    setActiveCitationTab("references");
  }, [reference?.id, referenceLineageId]);

  useEffect(() => {
    if (!referenceLineageId) {
      setCitationState({
        error: null,
        incoming: [],
        loaded: false,
        loading: false,
        outgoing: [],
      });
      return;
    }
    let active = true;
    setCitationState({
      error: null,
      incoming: [],
      loaded: false,
      loading: true,
      outgoing: [],
    });
    void loadReferenceCitationRelations({
      id: reference?.id ?? null,
      lineageId: referenceLineageId,
    })
      .then((result) => {
        if (!active) return;
        setCitationState({
          error: null,
          incoming: result.incoming,
          loaded: true,
          loading: false,
          outgoing: result.outgoing,
        });
      })
      .catch((error) => {
        if (!active) return;
        setCitationState({
          error: error instanceof Error ? error.message : "Could not load citation relations.",
          incoming: [],
          loaded: false,
          loading: false,
          outgoing: [],
        });
      });
    return () => {
      active = false;
    };
  }, [reference?.id, referenceLineageId]);

  const previewAttachments = useMemo(
    () => attachments.map((attachment) => ({
      ...attachment,
      sourceUri: attachmentLinksById[attachment.id] ?? attachment.sourceUri,
    })),
    [attachmentLinksById, attachments],
  );

  if (!reference) {
    return (
      <section className="category-steering-section" aria-label="Reference detail">
        <EmptyRow label="Select a reference to inspect curation details." />
      </section>
    );
  }

  const lineageId = referenceLineageId;
  const messages = graph.messagesFor("reference", lineageId);
  const insights = graph.insightsFor("reference", lineageId);
  const neighborGroups = graph.neighbors("reference", lineageId);
  const fallbackOutgoingCitationGroup = neighborGroups.find((group) => group.direction === "outgoing" && group.predicate === "cites") ?? null;
  const fallbackIncomingCitationGroup = neighborGroups.find((group) => group.direction === "incoming" && group.predicate === "cites") ?? null;
  const nonCitationNeighborGroups = neighborGroups.filter((group) => group.predicate !== "cites");
  const outgoingCitationRelations = citationState.loaded
    ? citationState.outgoing
    : (fallbackOutgoingCitationGroup?.relations ?? []);
  const incomingCitationRelations = citationState.loaded
    ? citationState.incoming
    : (fallbackIncomingCitationGroup?.relations ?? []);
  const outgoingCitationObjects = buildCitationReferenceObjects(graph, outgoingCitationRelations, "outgoing");
  const incomingCitationObjects = buildCitationReferenceObjects(graph, incomingCitationRelations, "incoming");
  const authors = reference.authors?.filter(Boolean).join(", ");
  const metadataPayload = modelPayloadByRole(referencePayloadState.payloads, "metadata");
  const metadataTitle = referenceMetadataTitle(metadataPayload) ?? reference.title ?? reference.externalItemId;
  const metadataSubtitle = normalizeReferenceDetailSubtitleForDisplay(
    referenceMetadataField(metadataPayload, reference.metadata, "subtitle"),
    reference.sourceUri,
  ) ?? "";
  const metadataSummary = normalizeReferenceDetailSummaryForDisplay(
    referenceDisplaySummary(graph, lineageId, metadataPayload, reference.metadata)
      ?? referenceMetadataField(metadataPayload, reference.metadata, "summary"),
    reference.sourceUri,
  ) ?? "";
  const detailCuration = curation ?? resolveReferenceCurationDisplayState(reference, graph);
  const activeExtractedTextEntry = extractedTextTabs.find((tab) => tab.mode === activeExtractedTextTab) ?? extractedTextTabs[0] ?? null;
  const activeExtractedTextState = activeExtractedTextEntry?.mode === "original"
    ? extractedTextOriginalState
    : extractedTextFilteredState;
  const inboundCitationCount = resolveReferenceCitationCount(reference.inboundCitationCount, incomingCitationRelations.length);
  const outboundCitationCount = resolveReferenceCitationCount(reference.outboundCitationCount, outgoingCitationRelations.length);

  return (
    <section className="category-steering-section" aria-label="Reference detail" data-news-desk-reference-detail={lineageId}>
      <article className="news-desk-semantic-detail">
        <header>
          <div>
            <strong>{metadataTitle}</strong>
            {metadataSubtitle ? <p className="news-desk-semantic-detail__subheading">{metadataSubtitle}</p> : null}
            <div className="news-desk-reference-detail__header-flow">
              <ReferenceCurationCluster
                curation={detailCuration}
                disabled={disabled}
                menuActions={curationMenuActions}
                qualityActionState={qualityActionState}
                onReview={onReview}
                onSetQualityRating={(rating) => onSetQualityRating(reference, rating)}
              />
              <p className="news-desk-reference-detail__meta-date-row">
                <span className="news-desk-reference-detail__meta-date-label">Published</span>
                <span className="news-desk-reference-detail__meta-date-value">{formatReferencePublishedDate(reference)}</span>
              </p>
              <p className="news-desk-reference-detail__meta-date-row">
                <span className="news-desk-reference-detail__meta-date-label">Imported</span>
                <span className="news-desk-reference-detail__meta-date-value">{formatReferenceImportedDate(reference)}</span>
              </p>
              {metadataSummary ? <p className="news-desk-semantic-detail__summary">{metadataSummary}</p> : null}
              {curationRunStatus ? (
                <div className="news-desk-detail-line">
                  <span>Curation</span>
                  <strong>{curationRunStatus.lifecycleStatus}</strong>
                </div>
              ) : null}
            </div>
          </div>
        </header>
        <KnowledgeQueryStatus error={knowledgeQuery.error} loading={knowledgeQuery.loading} />
        {knowledgeQuery.result ? (
          <KnowledgeQueryResultBlock result={knowledgeQuery.result} onClear={knowledgeQuery.clear} />
        ) : (
          <>
            <div className="news-desk-detail-block news-desk-detail-block--source-material">
              <p className="news-desk-reference-detail__source-meta-row">
                <span className="news-desk-reference-detail__source-meta-label">External ID</span>
                <span
                  className="news-desk-reference-detail__source-meta-value news-desk-reference-detail__source-meta-value--external-id"
                  title={reference.externalItemId}
                >
                  {reference.externalItemId}
                </span>
              </p>
              {authors ? <div className="news-desk-detail-line"><span>Authors</span><strong>{authors}</strong></div> : null}
              {reference.sourceUri ? (
                <p className="news-desk-reference-detail__source-meta-row news-desk-reference-detail__source-meta-row--uri">
                  <span className="news-desk-reference-detail__source-meta-label">Source URI</span>
                  <span
                    className="news-desk-reference-detail__source-meta-value news-desk-reference-detail__source-meta-value--uri news-desk-reference-detail__link-value"
                    data-news-desk-reference-source-uri-value
                    title={reference.sourceUri}
                  >
                    <a href={reference.sourceUri} rel="noopener noreferrer" target="_blank">{reference.sourceUri}</a>
                  </span>
                </p>
              ) : null}
              <ReferenceSourcePreview attachments={previewAttachments} sourceUri={reference.sourceUri} />
              <div className="news-desk-reference-detail__citation-summary" data-news-desk-reference-citation-summary>
                <div className="news-desk-reference-detail__citation-stat">
                  <span>Cited by</span>
                  <strong>{inboundCitationCount}</strong>
                </div>
                <div className="news-desk-reference-detail__citation-stat">
                  <span>References</span>
                  <strong>{outboundCitationCount}</strong>
                </div>
              </div>
              <ReferenceCorpusRow corpora={corpora} disabled={disabled} onMoveCorpus={onMoveCorpus} reference={reference} />
            </div>
            {curationRunStatus ? (
              <ReferenceCurationStatusPanel status={curationRunStatus} />
            ) : null}
            <ReferenceTopicLabelPanel
              categories={categories}
              categorySets={categorySets}
              disabled={disabled}
              onReviewTopicLabel={onReviewTopicLabel}
              reference={reference}
              semanticRelations={semanticRelations}
            />
            <ReferenceInsightPanel
              disabled={disabled}
              insights={insights}
              onCreateInsight={onCreateInsight}
              reference={reference}
            />
            <div data-news-desk-reference-metadata-expander>
              <NewsroomExpander
                className="news-desk-metadata-expander"
                label="Metadata"
                panelClassName="news-desk-metadata-expander__panel"
                panelInnerClassName="news-desk-metadata-expander__panel-inner"
                toggleClassName="newsroom-section-rail__rotating-toggle news-desk-metadata-expander__toggle"
              >
                <PayloadDetailBlock
                  fallback="Reference metadata is stored as metadata.json on S3."
                  hideLabel
                  label="Reference Metadata"
                  loading={referencePayloadState.loading}
                  payload={metadataPayload}
                  preferJson
                />
              </NewsroomExpander>
            </div>
            <div className="news-desk-detail-block news-desk-reference-extracted-text" data-news-desk-reference-extracted-text-section>
              <p className="story-label">Extracted Text</p>
              {extractedTextTabs.length ? (
                <>
                  <Tabs
                    defaultValue={extractedTextTabs[0].mode}
                    onValueChange={(value) => setActiveExtractedTextTab(value as ReferenceExtractedTextTab)}
                    value={activeExtractedTextEntry?.mode ?? extractedTextTabs[0].mode}
                  >
                    <TabsList
                      className="news-desk-reference-toggle__tabs"
                      data-news-desk-reference-extracted-text-tabs
                    >
                      {extractedTextTabs.map((tab) => (
                        <TabsTrigger
                          className="news-desk-reference-toggle__tab"
                          data-news-desk-reference-extracted-text-tab={tab.mode}
                          key={tab.mode}
                          value={tab.mode}
                        >
                          {tab.label}
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </Tabs>
                  <div
                    className="news-desk-reference-extracted-text__content"
                    data-news-desk-reference-extracted-text-content
                    data-news-desk-reference-extracted-text-active-tab={activeExtractedTextEntry?.mode ?? ""}
                  >
                    {activeExtractedTextState.loading ? (
                      <p
                        className="news-desk-detail-copy"
                        data-news-desk-reference-extracted-text-loading={activeExtractedTextEntry?.mode ?? ""}
                      >
                        Loading extracted text...
                      </p>
                    ) : null}
                    {!activeExtractedTextState.loading && activeExtractedTextState.error ? (
                      <p
                        className="news-desk-detail-copy"
                        data-news-desk-reference-extracted-text-error={activeExtractedTextEntry?.mode ?? ""}
                      >
                        {activeExtractedTextState.error}
                      </p>
                    ) : null}
                    {!activeExtractedTextState.loading && !activeExtractedTextState.error && activeExtractedTextState.text ? (
                      <MarkdownContext
                        className="news-desk-reference-extracted-text__markdown"
                        text={activeExtractedTextState.text}
                      />
                    ) : null}
                    {!activeExtractedTextState.loading && !activeExtractedTextState.error && !activeExtractedTextState.text ? (
                      <p
                        className="news-desk-detail-copy"
                        data-news-desk-reference-extracted-text-empty={activeExtractedTextEntry?.mode ?? ""}
                      >
                        Extracted text attachment is empty.
                      </p>
                    ) : null}
                  </div>
                </>
              ) : (
                <p
                  className="news-desk-detail-copy"
                  data-news-desk-reference-extracted-text-empty-state="both-missing"
                >
                  No extracted text attachments.
                </p>
              )}
            </div>
            <ReferenceCitationPanel
              activeTab={activeCitationTab}
              citationError={citationState.error}
              citationsLoading={citationState.loading}
              incomingObjects={incomingCitationObjects}
              inboundCitationCount={inboundCitationCount}
              onTabChange={setActiveCitationTab}
              outgoingObjects={outgoingCitationObjects}
              outboundCitationCount={outboundCitationCount}
            />
            {attachments.length ? (
              <div className="news-desk-detail-block">
                <p className="story-label">Attachments</p>
                {attachments.map((attachment) => (
                  <div className="news-desk-detail-line news-desk-reference-detail__attachment-line" key={attachment.id}>
                    <span>{attachment.role}</span>
                    <strong className="news-desk-reference-detail__link-value" data-news-desk-reference-attachment-path>
                      {attachmentLinksById[attachment.id] ? (
                        <a href={attachmentLinksById[attachment.id]} rel="noopener noreferrer" target="_blank">
                          {attachment.storagePath ?? attachment.sourceUri ?? attachment.filename ?? "unmapped file"}
                        </a>
                      ) : (attachment.storagePath ?? attachment.sourceUri ?? attachment.filename ?? "unmapped file")}
                    </strong>
                  </div>
                ))}
              </div>
            ) : null}
            {referencePayloadState.error ? <p className="news-desk-detail-copy">{referencePayloadState.error}</p> : null}
            {messages.length ? (
              <div className="news-desk-detail-block">
                <p className="story-label">Messages</p>
                {messages.slice(0, 4).map((message) => (
                  <div className="news-desk-detail-line" key={message.id}>
                    <span>{message.messageKind}</span>
                    <strong>
                      {message.messageKind === "reference_curation"
                        ? (metadataSummary ?? "Canonical summary unavailable")
                        : (message.summary ?? "Stored message payload")}
                    </strong>
                  </div>
                ))}
              </div>
            ) : null}
            <NeighborGroups groups={nonCitationNeighborGroups} />
          </>
        )}
      </article>
    </section>
  );
}

function ReferenceCitationPanel({
  activeTab,
  citationError,
  citationsLoading,
  incomingObjects,
  inboundCitationCount,
  onTabChange,
  outgoingObjects,
  outboundCitationCount,
}: {
  activeTab: ReferenceCitationTab;
  citationError: string | null;
  citationsLoading: boolean;
  incomingObjects: SemanticObjectSummary[];
  inboundCitationCount: number;
  onTabChange: (value: ReferenceCitationTab) => void;
  outgoingObjects: SemanticObjectSummary[];
  outboundCitationCount: number;
}) {
  return (
    <div className="news-desk-detail-block news-desk-reference-citations" data-news-desk-reference-citations>
      <p className="story-label">Citations</p>
      {citationsLoading ? <p className="news-desk-detail-copy">Loading citation graph...</p> : null}
      {citationError ? <p className="news-desk-detail-copy">{citationError}</p> : null}
      <Tabs defaultValue="references" onValueChange={(value) => onTabChange(value as ReferenceCitationTab)} value={activeTab}>
        <TabsList className="news-desk-reference-toggle__tabs">
          <TabsTrigger className="news-desk-reference-toggle__tab" value="references">References</TabsTrigger>
          <TabsTrigger className="news-desk-reference-toggle__tab" value="cited-by">Cited by</TabsTrigger>
        </TabsList>
        <TabsContent className="news-desk-reference-citations__content" value="references">
          <div className="news-desk-reference-citations__header">
            <strong>References</strong>
            <span>{outboundCitationCount}</span>
          </div>
          {outgoingObjects.length ? (
            <div className="news-desk-reference-citations__list">
              {outgoingObjects.map((object) => (
                <a
                  className="news-desk-reference-citations__item"
                  href={object.href}
                  key={`references-${object.kind}-${object.lineageId}`}
                >
                  <span>{object.kind}</span>
                  <strong>{object.label}</strong>
                </a>
              ))}
            </div>
          ) : <EmptyRow label="No cited references." />}
        </TabsContent>
        <TabsContent className="news-desk-reference-citations__content" value="cited-by">
          <div className="news-desk-reference-citations__header">
            <strong>Cited by</strong>
            <span>{inboundCitationCount}</span>
          </div>
          {incomingObjects.length ? (
            <div className="news-desk-reference-citations__list">
              {incomingObjects.map((object) => (
                <a
                  className="news-desk-reference-citations__item"
                  href={object.href}
                  key={`cited-by-${object.kind}-${object.lineageId}`}
                >
                  <span>{object.kind}</span>
                  <strong>{object.label}</strong>
                </a>
              ))}
            </div>
          ) : <EmptyRow label="No inbound citations yet." />}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function MessageDetailPanel({
  graph,
  knowledgeQuery,
  message,
  selected,
}: {
  graph: SemanticGraph;
  knowledgeQuery: KnowledgeQueryControl;
  message: MessageRecord;
  selected: SemanticObjectSummary | null;
}) {
  const messagePayloadState = useModelPayloads("message", message.id, ["message_body", "metadata"]);
  const bodyPayload = modelPayloadByRole(messagePayloadState.payloads, "message_body");
  const metadataPayload = modelPayloadByRole(messagePayloadState.payloads, "metadata");
  const messageMetadata = metadataRecord(metadataPayload?.json) ?? metadataRecord(message.metadata);
  const linkedReference = useReferenceCurationMessageReference(graph, message, messageMetadata);
  const referencePayloadState = useModelPayloads("reference", linkedReference?.id, ["metadata"]);
  const referenceMetadataPayload = modelPayloadByRole(referencePayloadState.payloads, "metadata");
  const referenceSubtitle = referenceMetadataSubtitle(referenceMetadataPayload, linkedReference?.metadata);
  const referenceSummary = linkedReference
    ? referenceDisplaySummary(
      graph,
      linkedReference.lineageId ?? linkedReference.id,
      referenceMetadataPayload,
      linkedReference.metadata,
    )
    : null;
  const headerLabel = humanizeNewsroomLabel(message.messageKind ?? "message");
  const headerTitle = message.messageKind === "reference_curation"
    ? linkedReference?.title ?? linkedReference?.externalItemId ?? "Reference curation"
    : message.summary ?? "Stored message payload";
  const detailSummary = message.messageKind === "reference_curation"
    ? referenceSummary ?? null
    : message.summary ?? null;
  const neighborGroups = selected ? graph.neighbors(selected.kind, selected.lineageId) : [];
  return (
    <section className="category-steering-section" aria-label="Message detail" data-news-desk-message-detail={message.id}>
      <article className="news-desk-semantic-detail">
        <header>
          <div>
            <p className="story-label">{headerLabel}</p>
            <strong data-news-desk-message-headline>{headerTitle}</strong>
            {message.messageKind === "reference_curation" && referenceSubtitle ? (
              <p className="news-desk-semantic-detail__subheading" data-news-desk-message-subheading>{referenceSubtitle}</p>
            ) : null}
            <span>{formatDateTime(message.createdAt)}</span>
          </div>
        </header>
        <KnowledgeQueryStatus error={knowledgeQuery.error} loading={knowledgeQuery.loading} />
        {knowledgeQuery.result ? (
          <KnowledgeQueryResultBlock result={knowledgeQuery.result} onClear={knowledgeQuery.clear} />
        ) : (
          <>
            <PayloadDetailBlock
              fallback="Message body is stored as a private S3 payload attachment."
              label="Body"
              loading={messagePayloadState.loading}
              payload={bodyPayload}
            />
            <div className="news-desk-detail-block">
              <p className="story-label">Message Metadata</p>
              {detailSummary ? (
                <div className="news-desk-detail-line" data-news-desk-message-summary>
                  <span>{message.messageKind === "reference_curation" ? "Summary" : "Event summary"}</span>
                  <strong>{detailSummary}</strong>
                </div>
              ) : null}
              <div className="news-desk-detail-line"><span>Status</span><strong>{message.status}</strong></div>
              <div className="news-desk-detail-line"><span>Source</span><strong>{message.source ?? "unknown"}</strong></div>
              <div className="news-desk-detail-line"><span>Author</span><strong>{message.authorLabel ?? message.authorSub ?? "unknown"}</strong></div>
              {linkedReference ? <div className="news-desk-detail-line"><span>Reference</span><strong>{linkedReference.title ?? linkedReference.externalItemId}</strong></div> : null}
              {message.importRunId ? <div className="news-desk-detail-line"><span>Import run</span><strong>{message.importRunId}</strong></div> : null}
            </div>
            <PayloadDetailBlock
              fallback="Message metadata is stored as metadata.json on S3."
              label="Structured Payload"
              loading={messagePayloadState.loading}
              payload={metadataPayload}
              preferJson
            />
            {messagePayloadState.error ? <p className="news-desk-detail-copy">{messagePayloadState.error}</p> : null}
            <NeighborGroups groups={neighborGroups} />
          </>
        )}
      </article>
    </section>
  );
}

function useReferenceCurationMessageReference(
  graph: ReturnType<typeof createSemanticGraphSnapshot>,
  message: MessageRecord,
  metadata: Record<string, unknown> | null,
): ReferenceRecord | null {
  const relationReferenceId = useMemo(
    () => referenceCurationMessageReferenceId(graph, message),
    [graph, message],
  );
  const graphReference = useMemo(
    () => resolveReferenceCurationMessageReference(graph, message, metadata),
    [graph, message, metadata],
  );
  const referenceId = relationReferenceId ?? normalizeMetadataString(metadata?.referenceId);
  const [loadedReference, setLoadedReference] = useState<ReferenceRecord | null>(null);

  useEffect(() => {
    setLoadedReference(null);
    if (message.messageKind !== "reference_curation" || graphReference || !referenceId) return;
    let active = true;
    loadReferenceRecordById(referenceId)
      .then((reference) => {
        if (active) setLoadedReference(reference);
      })
      .catch(() => {
        if (active) setLoadedReference(null);
      });
    return () => {
      active = false;
    };
  }, [graphReference, message.id, message.messageKind, referenceId]);

  return graphReference ?? loadedReference;
}

function resolveReferenceCurationMessageReference(
  graph: ReturnType<typeof createSemanticGraphSnapshot>,
  message: MessageRecord,
  metadata: Record<string, unknown> | null,
): ReferenceRecord | null {
  if (message.messageKind !== "reference_curation") return null;
  const outgoingReference = referenceCurationMessageRelation(graph, message);
  const graphSummary = outgoingReference
    ? graph.resolve("reference", outgoingReference.objectLineageId) ?? graph.resolve("reference", outgoingReference.objectId)
    : null;
  if (graphSummary?.kind === "reference" && graphSummary.record) {
    return graphSummary.record as ReferenceRecord;
  }
  const referenceId = normalizeMetadataString(metadata?.referenceId);
  const referenceLineageId = normalizeMetadataString(metadata?.referenceLineageId);
  const fallbackSummary = (referenceId ? graph.resolve("reference", referenceId) : null)
    ?? (referenceLineageId ? graph.resolve("reference", referenceLineageId) : null);
  return fallbackSummary?.kind === "reference" && fallbackSummary.record
    ? fallbackSummary.record as ReferenceRecord
    : null;
}

function referenceCurationMessageReferenceId(
  graph: ReturnType<typeof createSemanticGraphSnapshot>,
  message: MessageRecord,
): string | null {
  const relation = referenceCurationMessageRelation(graph, message);
  return relation?.objectId ?? null;
}

function referenceCurationMessageRelation(
  graph: ReturnType<typeof createSemanticGraphSnapshot>,
  message: MessageRecord,
): SemanticRelationRecord | null {
  if (message.messageKind !== "reference_curation") return null;
  return graph.outgoing("message", message.id)
    .find((relation) => relation.objectKind === "reference" && relationTypeKey(relation) === "comment")
    ?? null;
}

type ReferenceCurationDisplayState = {
  effectiveDisplayedStars: number;
  effectiveStatus: string;
  persistedQualityRating: number | null;
};

function referenceQualityActionStateFromRating(
  referenceId: string,
  rating: number,
  tone: ActionState["tone"],
  message: string,
): ReferenceQualityActionState {
  const accepted = rating >= 3;
  return {
    displayedStars: accepted ? rating : 0,
    effectiveStatus: accepted ? "accepted" : "rejected",
    message,
    referenceId,
    requestedRating: rating,
    showUnsetStars: false,
    tone,
  };
}

function referenceQualityActionStateFromConfirmed(
  referenceId: string,
  requestedRating: number,
  curation: ReferenceCurationDisplayState,
  tone: ActionState["tone"],
  message: string,
): ReferenceQualityActionState {
  const rejected = curation.effectiveStatus === "rejected";
  return {
    displayedStars: rejected ? 0 : curation.effectiveDisplayedStars,
    effectiveStatus: curation.effectiveStatus,
    message,
    referenceId,
    requestedRating,
    showUnsetStars: !rejected && curation.persistedQualityRating === null,
    tone,
  };
}

function shouldFailReferenceQualityMutationForTest(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem("papyrus:test-reference-quality-mutation") === "fail";
  } catch {
    return false;
  }
}

function ReferenceCurationCluster({
  curation,
  disabled,
  menuActions = [],
  qualityActionState,
  onReview,
  onSetQualityRating,
}: {
  curation: ReferenceCurationDisplayState;
  disabled: boolean;
  menuActions?: NewsroomDetailAction[];
  qualityActionState: ReferenceQualityActionState | null;
  onReview: (action: ReferenceCurationAction) => void;
  onSetQualityRating: (rating: number) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const status = qualityActionState?.effectiveStatus ?? curation.effectiveStatus;
  const showUnsetStars = qualityActionState?.showUnsetStars ?? (status !== "rejected" && curation.persistedQualityRating === null);
  const filledStars = qualityActionState?.displayedStars ?? (status === "rejected" ? 0 : curation.effectiveDisplayedStars);
  const qualityTone = qualityActionState?.tone ?? "idle";
  const qualityPending = qualityTone === "pending";
  const clusterDisabled = disabled || qualityPending;
  const acceptDisabled = clusterDisabled || status === "accepted";
  const rejectDisabled = clusterDisabled || status === "rejected";
  const statusLabel = status === "accepted" ? "Accepted" : status === "rejected" ? "Rejected" : null;
  const resolvedMenuActions: NewsroomDetailAction[] = [
    ...menuActions,
    ...(status !== "archived" ? [{
      key: "archive",
      icon: <ArchiveIcon />,
      label: "Archive",
      onSelect: () => onReview("archive"),
    } satisfies NewsroomDetailAction] : []),
  ];

  useEffect(() => {
    if (!menuOpen) return;
    function handlePointerDown(event: PointerEvent) {
      if (menuRef.current?.contains(event.target as Node)) return;
      setMenuOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  return (
    <div
      className="news-desk-reference-curation-cluster"
      data-news-desk-reference-curation-cluster
      data-reference-curation-status={status}
      data-reference-quality-stars={filledStars}
      data-reference-quality-tone={qualityTone}
      data-reference-quality-unset={showUnsetStars ? "true" : "false"}
    >
      <div className="news-desk-reference-curation-cluster__row">
        {statusLabel ? <span className="news-desk-reference-curation-cluster__status-label">{statusLabel}</span> : null}
        <button
          type="button"
          aria-label="Accept reference"
          aria-pressed={status === "accepted"}
          className="news-desk-detail-toolbar-button news-desk-reference-curation-cluster__decision"
          data-news-desk-reference-accept
          disabled={acceptDisabled}
          onClick={() => onReview("accept")}
          title="Accept"
        >
          <ThumbsUpIcon />
          {!acceptDisabled ? <span>Accept</span> : null}
        </button>
        <button
          type="button"
          aria-label="Reject reference"
          aria-pressed={status === "rejected"}
          className="news-desk-detail-toolbar-button news-desk-reference-curation-cluster__decision"
          data-news-desk-reference-reject
          disabled={rejectDisabled}
          onClick={() => onReview("reject")}
          title="Reject"
        >
          <ThumbsDownIcon />
          {!rejectDisabled ? <span>Reject</span> : null}
        </button>
        <div
          className="news-desk-reference-curation-cluster__stars"
          data-reference-quality-stars-control
          data-reference-quality-tone={qualityTone}
          role="group"
          aria-busy={qualityPending ? "true" : undefined}
          aria-label="Reference quality rating"
        >
          {[1, 2, 3, 4, 5].map((rating) => {
            const filled = !showUnsetStars && rating <= filledStars;
            return (
              <button
                type="button"
                aria-label={`Set ${rating} star quality`}
                aria-pressed={filled}
                className="news-desk-reference-curation-cluster__star"
                data-filled={filled ? "true" : undefined}
                data-news-desk-reference-quality-star={rating}
                disabled={clusterDisabled}
                key={rating}
                onClick={() => onSetQualityRating(rating)}
                title={`${rating} star${rating === 1 ? "" : "s"}`}
              >
                <StarIcon filled={filled} />
              </button>
            );
          })}
        </div>
        {resolvedMenuActions.length ? (
          <div className="newsroom-list-detail-shell__action-menu-wrap" ref={menuRef}>
            <button
              type="button"
              aria-label="Reference curation actions"
              aria-expanded={menuOpen}
              className="news-desk-detail-toggle news-desk-detail-toggle--actions"
              data-news-desk-reference-actions
              disabled={clusterDisabled}
              onClick={() => setMenuOpen((current) => !current)}
            >
              <EllipsisIcon />
            </button>
            {menuOpen ? (
              <div className="newsroom-list-detail-shell__action-menu" role="menu">
                {resolvedMenuActions.map((action) => (
                  <button
                    type="button"
                    disabled={clusterDisabled || action.disabled}
                    key={action.key}
                    onClick={() => {
                      setMenuOpen(false);
                      action.onSelect();
                    }}
                    role="menuitem"
                  >
                    {action.icon ? <span className="newsroom-list-detail-shell__action-menu-icon">{action.icon}</span> : null}
                    <span>{action.label}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      <span
        className="news-desk-reference-curation-cluster__quality-state"
        data-reference-quality-state-message
        data-tone={qualityTone}
        aria-live="polite"
      >
        {qualityActionState?.message ?? ""}
      </span>
    </div>
  );
}

function ReferenceCurationPanel({
  attachments = [],
  disabled,
  onReasonCodeChange,
  reasonCode,
  reference,
}: {
  attachments?: ReferenceAttachmentRecord[];
  disabled: boolean;
  onReasonCodeChange: (reasonCode: ReferenceRejectionReasonCode) => void;
  reasonCode: ReferenceRejectionReasonCode;
  reference: ReferenceRecord;
}) {
  const processingStatus = resolveReferenceProcessingStatus(reference, attachments);
  const status = reference.curationStatus ?? "pending";
  return (
    <div className="news-desk-detail-block" data-reference-curation-status={status} data-reference-processing-status={processingStatus}>
      <p className="story-label">Reference Curation</p>
      <div className="news-desk-detail-line">
        <span>Processing</span>
        <strong>{processingStatus}</strong>
      </div>
      <div className="news-desk-detail-line">
        <span>Curation</span>
        <strong>{status}</strong>
      </div>
      {reference.curationStatusReason ? (
        <div className="news-desk-detail-line">
          <span>Reason</span>
          <strong>{reference.curationStatusReason}</strong>
        </div>
      ) : null}
      <label className="news-desk-reference-curation-note">
        <span>Rejection reason</span>
        <select
          disabled={disabled}
          value={reasonCode}
          onChange={(event) => onReasonCodeChange(event.target.value as ReferenceRejectionReasonCode)}
        >
          {REFERENCE_REJECTION_REASON_CODES.map((code) => (
            <option key={code} value={code}>{referenceReasonLabel(code)}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

function ReferenceTopicLabelPanel({
  categories,
  categorySets,
  disabled,
  onReviewTopicLabel,
  reference,
  semanticRelations,
}: {
  categories: CategorySteeringCategory[];
  categorySets: CategorySteeringCategorySet[];
  disabled: boolean;
  onReviewTopicLabel: (input: { action: TopicLabelAction; category: CategorySteeringCategory; note?: string | null; reference: ReferenceRecord; sourceRelationId?: string | null }) => void;
  reference: ReferenceRecord;
  semanticRelations: SemanticRelationRecord[];
}) {
  const [categoryId, setCategoryId] = useState("");
  const [note, setNote] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const currentCategorySetIds = new Set(categorySets.filter((set) => set.versionState === "current" || set.versionState === "draft").map((set) => set.id));
  const labelableCategories = categories
    .filter((category) => currentCategorySetIds.has(category.categorySetId))
    .filter((category) => category.status !== "deprecated" && category.status !== "archived")
    .sort((left, right) => (left.depth ?? 0) - (right.depth ?? 0) || left.displayName.localeCompare(right.displayName));
  const selectedCategory = labelableCategories.find((category) => category.id === categoryId) ?? null;
  const referenceLineageId = reference.lineageId ?? reference.id;
  const relations = semanticRelations.filter((relation) => (
    relation.relationState === "current"
    && relation.subjectKind === "reference"
    && (relation.subjectId === reference.id || relation.subjectLineageId === referenceLineageId)
    && ["classified_as", "authoritative_label"].includes(semanticRelationKind(relation))
  ));
  const canLabel = isCurrentAcceptedReferenceRecord(reference);
  const relationRows = relations.map((relation) => {
    const category = categories.find((entry) => entry.id === relation.objectId || entry.lineageId === relation.objectLineageId) ?? null;
    const relationKind = semanticRelationKind(relation);
    const metadata = metadataRecord(relation.metadata);
    const explanation = normalizeMetadataString(metadata?.explanation)
      ?? normalizeMetadataString(metadata?.reason)
      ?? normalizeMetadataString(metadata?.note);
    const source = relation.importRunId
      ? `import ${relation.importRunId}`
      : relation.classifierId
        ? `classifier ${relation.classifierId}`
        : relationKind === "authoritative_label"
          ? "editor"
          : "system";
    return {
      category,
      explanation,
      relation,
      relationKind,
      source,
    };
  });

  return (
    <section className="news-desk-reference-workflow" data-reference-topic-workflow>
      <header className="news-desk-reference-workflow__header">
        <p className="story-label">Topic Labels</p>
        {canLabel && !composerOpen ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => {
              setComposerOpen(true);
            }}
          >
            Add topic
          </button>
        ) : null}
      </header>
      <div className="news-desk-reference-workflow__columns">
        <div className="news-desk-reference-workflow__state" data-reference-topic-state>
          {relationRows.length ? relationRows.map((row) => (
            <article className="news-desk-reference-topic-state-row" key={row.relation.id}>
              <div className="news-desk-reference-topic-state-row__headline">
                <strong>{row.category?.displayName ?? row.relation.objectId}</strong>
                <span>{row.relationKind === "authoritative_label" ? "Authoritative label" : "Predicted topic"}</span>
              </div>
              <div className="news-desk-reference-topic-state-row__meta">
                <span>{row.source}</span>
                {row.explanation ? <p>{row.explanation}</p> : <p>No explanation attached.</p>}
              </div>
            </article>
          )) : null}
        </div>
        <div className="news-desk-reference-workflow__input" data-reference-topic-input>
          {!canLabel ? <p className="news-desk-detail-copy">Only current accepted references can receive authoritative labels.</p> : null}
          {canLabel && composerOpen ? (
            <form
              className="news-desk-reference-topic-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (disabled || !selectedCategory) return;
                onReviewTopicLabel({ action: "manual_label", category: selectedCategory, reference, note });
                setCategoryId("");
                setNote("");
                setComposerOpen(false);
              }}
            >
              <label className="news-desk-reference-curation-note">
                <span>Topic</span>
                <select disabled={disabled} value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
                  <option value="">Select topic</option>
                  {labelableCategories.map((category) => {
                    const categorySet = categorySets.find((set) => set.id === category.categorySetId);
                    return (
                      <option key={category.id} value={category.id}>
                        {category.depth ? " - " : ""}{category.displayName} ({categorySet?.versionState ?? "set"})
                      </option>
                    );
                  })}
                </select>
              </label>
              <label className="news-desk-reference-curation-note">
                <span>Rationale</span>
                <input disabled={disabled} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why this reference is a seed example" />
              </label>
              <div className="news-desk-reference-topic-form__actions">
                <button type="submit" disabled={disabled || !selectedCategory}>
                  Add topic
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    setComposerOpen(false);
                    setCategoryId("");
                    setNote("");
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : null}
          {relationRows.length ? (
            <div className="news-desk-reference-topic-actions">
              {relationRows.map((row) => {
                const category = row.category;
                return (
                  <div className="news-desk-reference-topic-actions__row" key={`actions-${row.relation.id}`}>
                    <strong>{category?.displayName ?? row.relation.objectId}</strong>
                    {row.relationKind === "authoritative_label" && category ? (
                      <button type="button" disabled={disabled} onClick={() => onReviewTopicLabel({ action: "unlabel", category, reference, sourceRelationId: row.relation.id })}>Remove</button>
                    ) : null}
                    {row.relationKind === "classified_as" && category ? (
                      <>
                        <button type="button" disabled={disabled || !canLabel} onClick={() => onReviewTopicLabel({ action: "accept_prediction", category, reference, sourceRelationId: row.relation.id })}>Accept</button>
                        <button type="button" disabled={disabled} onClick={() => onReviewTopicLabel({ action: "reject_prediction", category, reference, sourceRelationId: row.relation.id })}>Reject</button>
                      </>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ReferenceCorpusRow({
  corpora,
  disabled,
  onMoveCorpus,
  reference,
}: {
  corpora: CategorySteeringCorpus[];
  disabled: boolean;
  onMoveCorpus: (reference: ReferenceRecord, corpusId: string) => void;
  reference: ReferenceRecord;
}) {
  const [selectedCorpusId, setSelectedCorpusId] = useState(reference.corpusId);
  useEffect(() => {
    setSelectedCorpusId(reference.corpusId);
  }, [reference.corpusId, reference.id]);
  const selectableCorpora = corpora.length
    ? corpora
    : [{ id: reference.corpusId, name: reference.corpusId, role: "source" }];
  return (
    <p className="news-desk-reference-detail__source-meta-row news-desk-reference-detail__source-meta-row--corpus">
      <span className="news-desk-reference-detail__source-meta-label">Corpus</span>
      <span className="news-desk-reference-detail__source-meta-value news-desk-reference-detail__source-meta-value--control">
        <span className="news-desk-reference-corpus-control news-desk-reference-corpus-control--inline" data-reference-corpus-input>
          <select
            aria-label="Corpus"
            disabled={disabled}
            value={selectedCorpusId}
            onChange={(event) => {
              const nextCorpusId = event.target.value;
              setSelectedCorpusId(nextCorpusId);
              if (nextCorpusId !== reference.corpusId) onMoveCorpus(reference, nextCorpusId);
            }}
          >
            {selectableCorpora.map((entry) => (
              <option key={entry.id} value={entry.id}>{entry.name}</option>
            ))}
          </select>
          <span className="news-desk-reference-corpus-control__icon" aria-hidden="true">
            <RotatingSectionTriangleIcon expanded />
          </span>
        </span>
      </span>
    </p>
  );
}

function ReferenceCurationStatusPanel({ status }: { status: ReferenceCurationRunStatus }) {
  const stageOrder = ["identifier", "publicationDate", "titleSubtitle", "summary", "topicPredictions"];
  return (
    <section className="news-desk-reference-workflow" data-reference-curation-status-panel>
      <header className="news-desk-reference-workflow__header">
        <p className="story-label">Re-curation Run</p>
      </header>
      <div className="news-desk-reference-workflow__state">
        <div className="news-desk-detail-line"><span>Lifecycle</span><strong>{status.lifecycleStatus}</strong></div>
        <div className="news-desk-detail-line"><span>Assignment</span><strong>{status.assignmentId}</strong></div>
        <div className="news-desk-detail-line"><span>Updated</span><strong>{formatDateTime(status.updatedAt)}</strong></div>
        {stageOrder.map((stageKey) => {
          const stageValue = status.stageStatuses[stageKey];
          const stageRecord = stageValue && typeof stageValue === "object" && !Array.isArray(stageValue)
            ? stageValue as Record<string, unknown>
            : {};
          const stageState = normalizeMetadataString(stageRecord.status) ?? "unknown";
          return (
            <div className="news-desk-detail-line" key={stageKey}>
              <span>{stageKey}</span>
              <strong>{stageState}</strong>
            </div>
          );
        })}
        {status.error ? (
          <div className="news-desk-detail-line">
            <span>Error</span>
            <strong>{normalizeMetadataString(status.error.message) ?? "Unknown error"}</strong>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ReferenceInsightPanel({
  disabled,
  insights,
  onCreateInsight,
  reference,
}: {
  disabled: boolean;
  insights: MessageRecord[];
  onCreateInsight: (target: InsightTarget, summary: string, body: string) => Promise<void>;
  reference: ReferenceRecord;
}) {
  const [composerOpen, setComposerOpen] = useState(false);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const target = useMemo(() => insightTargetForReference(reference), [reference]);
  const hasInsights = insights.length > 0;

  return (
    <section className="news-desk-reference-workflow" data-reference-insight-workflow>
      <header className="news-desk-reference-workflow__header">
        <p className="story-label">Insights</p>
        {!hasInsights && !composerOpen ? (
          <button
            type="button"
            data-news-desk-reference-insight-trigger
            disabled={disabled || saving}
            onClick={() => {
              setComposerOpen(true);
              setError(null);
            }}
          >
            Add insight
          </button>
        ) : null}
      </header>
      <div className="news-desk-reference-insight-shell" data-reference-insight-input>
        {hasInsights ? (
          <div className="news-desk-reference-insight-list" data-reference-insight-state>
            {insights.map((message) => (
              <article className="news-desk-reference-topic-state-row" key={message.id}>
                <div className="news-desk-reference-topic-state-row__headline">
                  <strong>{message.summary ?? "Stored insight"}</strong>
                  <span>{message.authorLabel ?? message.source ?? "knowledge"}</span>
                </div>
                <div className="news-desk-reference-topic-state-row__meta">
                  <span>{formatDateTime(message.createdAt)}</span>
                </div>
              </article>
            ))}
          </div>
        ) : null}
        {hasInsights && !composerOpen ? (
          <button
            type="button"
            data-news-desk-reference-insight-trigger
            disabled={disabled || saving}
            onClick={() => {
              setComposerOpen(true);
              setError(null);
            }}
          >
            Add insight
          </button>
        ) : null}
        {composerOpen ? (
          <form
            className="news-desk-reference-insight-form"
            data-news-desk-reference-insight-form
            onSubmit={(event) => {
              event.preventDefault();
              if (disabled || saving) return;
              const cleanBody = body.trim();
              if (!cleanBody) {
                setError("Insight text is required.");
                return;
              }
              const cleanSummary = summarizeInsightForStorage(cleanBody);
              setSaving(true);
              setError(null);
              void onCreateInsight(target, cleanSummary, cleanBody)
                .then(() => {
                  setSaving(false);
                  setBody("");
                  setComposerOpen(false);
                })
                .catch((submitError) => {
                  setSaving(false);
                  setError(submitError instanceof Error ? submitError.message : "Could not save insight.");
                });
            }}
          >
              <label className="news-desk-reference-curation-note">
                <span>Insight</span>
                <textarea
                  disabled={disabled || saving}
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                />
              </label>
            {error ? <p className="news-desk-detail-copy">{error}</p> : null}
            <div className="news-desk-reference-insight-form__actions">
              <button type="submit" disabled={disabled || saving || !body.trim()}>
                {saving ? "Saving" : "Save insight"}
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  setComposerOpen(false);
                  setBody("");
                  setError(null);
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}

function summarizeInsightForStorage(body: string): string {
  const normalized = body.trim().replace(/\s+/g, " ");
  if (!normalized) return "Insight";
  const firstSentenceMatch = normalized.match(/(.+?[.!?])(?:\s|$)/);
  const candidate = (firstSentenceMatch?.[1] ?? normalized).trim();
  if (candidate.length <= 120) return candidate;
  return `${candidate.slice(0, 117).trimEnd()}...`;
}

function NeighborGroups({ groups }: { groups: SemanticNeighborGroup[] }) {
  return (
    <div className="news-desk-detail-block" data-news-desk-neighbors>
      <p className="story-label">Semantic Neighbors</p>
      {groups.length ? groups.map((group) => (
        <div className="news-desk-neighbor-group" key={`${group.direction}-${group.predicate}`}>
          <header>
            <strong>{group.label}</strong>
            <span>{group.direction} / {group.relations.length}</span>
          </header>
          {group.objects.map((object) => (
            <a href={object.href} key={`${group.direction}-${group.predicate}-${object.kind}-${object.lineageId}`}>
              <span>{object.kind}</span>
              <strong>{object.label}</strong>
            </a>
          ))}
        </div>
      )) : <EmptyRow label="No current semantic relations for this object" />}
    </div>
  );
}

function DeskLinkCard({ href, label, value, detail }: { href: string; label: string; value: number; detail: string }) {
  return (
    <Link className="news-desk-ledger-item news-desk-ledger-item--link" href={href}>
      <header>
        <strong>{label}</strong>
        <span>{value}</span>
      </header>
      <p>{detail}</p>
    </Link>
  );
}

function AssignmentDeskView({
  actionState,
  analysisProfiles,
  assignmentEvents,
  assignments,
  editionSlots,
  corpora,
  messages,
  graph,
  semanticRelations,
  initialAssignmentId,
  initialView,
  isDemo,
  newsroomSections,
  summary,
  disabled,
  onAction,
  onCreateAnalysisReindexAssignment,
  onReviewReportingPacket,
}: {
  actionState: ActionState | null;
  analysisProfiles: AnalysisProfileSummary[];
  assignmentEvents: AssignmentEventRecord[];
  assignments: AssignmentRecord[];
  editionSlots: EditionSlotRecord[];
  corpora: CategorySteeringCorpus[];
  messages: MessageRecord[];
  graph: SemanticGraph;
  semanticRelations: SemanticRelationRecord[];
  initialAssignmentId?: string | null;
  initialView?: string | null;
  isDemo?: boolean;
  newsroomSections: NewsroomSectionRecord[];
  summary?: NewsroomSummaryRecord | null;
  disabled: boolean;
  onAction: (assignment: AssignmentRecord, action: AssignmentAction, note?: string) => void;
  onCreateAnalysisReindexAssignment: (profile: AnalysisProfileSummary, draft: AnalysisReindexDraft) => void;
  onReviewReportingPacket: (assignment: AssignmentRecord, packet: AssignmentResearchPacketSummary, decision: ReportingPacketReviewDecision, note?: string, targetItemId?: string) => void;
}) {
  const [assignmentTypeFilter, setAssignmentTypeFilter] = useState(() => {
    if (typeof window === "undefined") return "";
    return readAssignmentsIndexFilters(new URLSearchParams(window.location.search)).type;
  });
  const [assignmentStatusFilter, setAssignmentStatusFilter] = useState(() => {
    if (typeof window === "undefined") return "";
    return readAssignmentsIndexFilters(new URLSearchParams(window.location.search)).status;
  });
  const [isCreateAssignmentOpen, setIsCreateAssignmentOpen] = useState(false);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState(initialAssignmentId ?? "");
  const [isAssignmentDetailOpen, setIsAssignmentDetailOpen] = useState(Boolean(initialAssignmentId));
  const [assignmentDeskView, setAssignmentDeskView] = useState<AssignmentDeskViewMode>(() => {
    if (initialView === "budget") return "budget";
    if (typeof window === "undefined") return "queue";
    const view = readAssignmentsIndexFilters(new URLSearchParams(window.location.search)).view;
    return view === "budget" ? "budget" : "queue";
  });
  const [assignmentActionNote, setAssignmentActionNote] = useState("");
  const [reportingMergeTargetItemId, setReportingMergeTargetItemId] = useState("");
  const syncAssignmentsIndexUrl = useCallback((
    nextStatus: string,
    nextType: string,
    nextView: AssignmentDeskViewMode,
    replace = true,
  ) => {
    if (isDemo || isAssignmentDetailOpen) return;
    syncBrowserNewsroomIndexUrl(
      "assignments",
      effectiveAssignmentsIndexFilters({
        status: nextStatus,
        type: nextType,
        view: nextView,
      }),
      { replace },
    );
  }, [isAssignmentDetailOpen, isDemo]);
  useEffect(() => {
    if (isDemo || isAssignmentDetailOpen || assignmentDeskView === "budget") return;
    syncAssignmentsIndexUrl(assignmentStatusFilter, assignmentTypeFilter, assignmentDeskView, true);
  }, [
    assignmentDeskView,
    assignmentStatusFilter,
    assignmentTypeFilter,
    isAssignmentDetailOpen,
    isDemo,
    syncAssignmentsIndexUrl,
  ]);
  const feed = useNewsroomPagedRows({
    initialItems: assignments,
    enabled: !isDemo,
    resetKey: `assignments:${assignmentTypeFilter}:${assignmentStatusFilter}`,
    loadPage: (nextToken) => loadNewsroomAssignmentPage({
      type: assignmentTypeFilter,
      status: assignmentStatusFilter,
      nextToken,
    }),
  });
  const feedAssignments = isDemo ? assignments : feed.items;
  const assignmentTypeOptions = useMemo(() => getAssignmentTypeOptions(assignments, summary), [assignments, summary]);
  const typeFilteredAssignments = useMemo(() => (
    assignmentTypeFilter
      ? feedAssignments.filter((assignment) => assignmentTypeKeyForFilter(assignment) === assignmentTypeFilter)
      : feedAssignments
  ), [assignmentTypeFilter, feedAssignments]);
  const filteredAssignments = useMemo(() => {
    const filtered = assignmentStatusFilter
      ? typeFilteredAssignments.filter((assignment) => assignment.status === assignmentStatusFilter)
      : typeFilteredAssignments;
    return [...filtered].sort(compareAssignments);
  }, [assignmentStatusFilter, typeFilteredAssignments]);
  const filteredMetrics = getAssignmentMetrics(typeFilteredAssignments, summary, assignmentTypeFilter);
  const totalAssignmentCount = summaryCountFromRecord(summary, "assignments") || assignments.length;
  const requestedAssignmentId = selectedAssignmentId || initialAssignmentId || "";
  const selectedAssignment = requestedAssignmentId
    ? filteredAssignments.find((assignment) => assignment.id === requestedAssignmentId)
      ?? typeFilteredAssignments.find((assignment) => assignment.id === requestedAssignmentId)
      ?? feedAssignments.find((assignment) => assignment.id === requestedAssignmentId)
      ?? assignments.find((assignment) => assignment.id === requestedAssignmentId)
      ?? null
    : null;
  const assignmentKnowledgeQuery = useNewsroomKnowledgeContext(selectedAssignment ? {
    anchor: { kind: "assignment", id: selectedAssignment.id },
    title: selectedAssignment.title,
    subtitle: selectedAssignment.assignmentTypeKey,
  } : null);
  const selectAssignment = (assignmentId: string) => {
    setSelectedAssignmentId(assignmentId);
    setIsAssignmentDetailOpen(true);
    pushNewsroomDetailUrl("assignments", assignmentId, isDemo);
  };
  const selectedAssignmentTerminal = selectedAssignment?.status === "completed" || selectedAssignment?.status === "canceled";
  const selectedReportingPackets = selectedAssignment ? reportingPacketsForAssignment(selectedAssignment, graph, messages) : [];
  const selectedReportingPacket = selectedReportingPackets[0] ?? null;
  const selectedReportingDecision = selectedAssignment ? latestReportingPacketDecisionForAssignment(assignmentEvents, selectedAssignment.id) : null;
  const storyBudget = useMemo(() => buildReportingStoryBudget({
    assignments,
    messages,
    assignmentEvents,
    semanticRelations,
    editionSlots,
    newsroomSections,
  }), [assignmentEvents, assignments, editionSlots, messages, newsroomSections, semanticRelations]);
  const runAssignmentDetailAction = (action: AssignmentAction) => {
    if (!selectedAssignment) return;
    onAction(selectedAssignment, action, assignmentActionNote);
    setAssignmentActionNote("");
  };
  const runReportingReviewAction = (decision: ReportingPacketReviewDecision) => {
    if (!selectedAssignment || !selectedReportingPacket) return;
    onReviewReportingPacket(selectedAssignment, selectedReportingPacket, decision, assignmentActionNote, reportingMergeTargetItemId);
    setAssignmentActionNote("");
  };
  const selectAssignmentDeskView = (view: AssignmentDeskViewMode) => {
    setAssignmentDeskView(view);
    if (typeof window === "undefined" || isDemo) return;
    syncBrowserNewsroomIndexUrl(
      "assignments",
      effectiveAssignmentsIndexFilters({
        status: assignmentStatusFilter,
        type: assignmentTypeFilter,
        view,
      }),
      { replace: true },
    );
  };
  const runStoryBudgetReviewAction = (candidate: ReportingStoryBudgetCandidate, decision: ReportingPacketReviewDecision) => {
    const assignment = assignments.find((entry) => entry.id === candidate.assignmentId);
    const packet = assignment ? reportingPacketsForAssignment(assignment, graph, messages)[0] : null;
    if (!assignment || !packet) return;
    onReviewReportingPacket(assignment, packet, decision, "", candidate.targetItemId ?? "");
    setSelectedAssignmentId(assignment.id);
    setIsAssignmentDetailOpen(true);
  };
  const assignmentActions: NewsroomDetailAction[] = selectedAssignment ? [
    ...(selectedAssignment.status === "open"
      ? [
          {
            key: "claim",
            label: "Claim",
            disabled,
            onSelect: () => runAssignmentDetailAction("claim"),
          },
          ...(assignmentExecutionModeForUi(selectedAssignment.assignmentTypeKey) === "immediate"
            ? [
                {
                  key: "retry",
                  label: "Retry Immediate",
                  disabled,
                  onSelect: () => runAssignmentDetailAction("retry"),
                },
              ]
            : []),
        ]
      : []),
    ...(selectedAssignment.status === "claimed"
      ? [
          {
            key: "release",
            label: "Release",
            disabled,
            onSelect: () => runAssignmentDetailAction("release"),
          },
        ]
      : []),
    ...(!selectedAssignmentTerminal
      ? [
          {
            key: "complete",
            label: "Complete",
            disabled,
            onSelect: () => runAssignmentDetailAction("complete"),
          },
          {
            key: "cancel",
            label: "Cancel",
            disabled,
            onSelect: () => runAssignmentDetailAction("cancel"),
          },
        ]
      : [
          {
            key: "reopen",
            label: "Reopen",
            disabled,
            onSelect: () => runAssignmentDetailAction("reopen"),
          },
        ]),
  ] : [];
  const reportingReviewActions: NewsroomDetailAction[] = selectedAssignment && selectedReportingPacket ? [
    {
      key: "reporting-select",
      label: "Select Packet",
      disabled,
      onSelect: () => runReportingReviewAction("select"),
    },
    {
      key: "reporting-brief",
      label: "Make Brief",
      disabled,
      onSelect: () => runReportingReviewAction("brief"),
    },
    {
      key: "reporting-merge",
      label: "Merge Packet",
      disabled: disabled || !reportingMergeTargetItemId.trim(),
      onSelect: () => runReportingReviewAction("merge"),
    },
    {
      key: "reporting-hold",
      label: "Hold Packet",
      disabled,
      onSelect: () => runReportingReviewAction("hold"),
    },
    {
      key: "reporting-kill",
      label: "Kill Packet",
      disabled,
      onSelect: () => runReportingReviewAction("kill"),
    },
  ] : [];

  useEffect(() => {
    if (assignmentTypeFilter && !assignmentTypeOptions.some((option) => option.key === assignmentTypeFilter)) {
      setAssignmentTypeFilter("");
    }
  }, [assignmentTypeFilter, assignmentTypeOptions]);

  useEffect(() => {
    if (assignmentStatusFilter && !["open", "claimed", "completed", "canceled"].includes(assignmentStatusFilter)) {
      setAssignmentStatusFilter("");
    }
  }, [assignmentStatusFilter]);

  useEffect(() => {
    setAssignmentActionNote("");
    setReportingMergeTargetItemId("");
  }, [selectedAssignment?.id, selectedAssignment?.status]);

  useEffect(() => {
    if (!isCreateAssignmentOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsCreateAssignmentOpen(false);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isCreateAssignmentOpen]);

  return (
    <>
      <NewsroomListDetailShell
        animatedDetail
        sectionKey="assignments"
        canExpandDetail={Boolean(selectedAssignment)}
        detailOpen={isAssignmentDetailOpen}
        selectionScrollKey={selectedAssignment?.id ?? null}
        actions={assignmentActions}
        utilityActions={[assignmentKnowledgeQuery.action, ...reportingReviewActions]}
        lede={(
          <NewsroomDeskSectionLede
            headingId="assignment-management-title"
            section="assignments"
            controls={(
              <div className="news-desk-assignment-create-strip">
                <div className="news-desk-assignment-view-toggle" role="group" aria-label="Assignment view">
                  <button
                    type="button"
                    data-active={assignmentDeskView === "queue" || undefined}
                    onClick={() => selectAssignmentDeskView("queue")}
                  >
                    Queue
                  </button>
                  <button
                    type="button"
                    data-active={assignmentDeskView === "budget" || undefined}
                    onClick={() => selectAssignmentDeskView("budget")}
                  >
                    Story Budget
                  </button>
                </div>
                <button
                  type="button"
                  className="news-desk-assignment-create-button"
                  disabled={disabled}
                  onClick={() => setIsCreateAssignmentOpen(true)}
                >
                  Create Assignment
                </button>
              </div>
            )}
          />
        )}
        list={(
          <section className="category-steering-section category-steering-section--lead" aria-label="Assignments queue">
            {assignmentDeskView === "budget" ? (
              <ReportingStoryBudgetBoard
                budget={storyBudget}
                disabled={disabled}
                onReview={runStoryBudgetReviewAction}
                onSelect={selectAssignment}
                selectedAssignmentId={selectedAssignment?.id ?? null}
              />
            ) : (
              <AssignmentManagementGrid
                assignmentEvents={assignmentEvents}
                assignments={filteredAssignments}
                metrics={filteredMetrics}
                onSelect={selectAssignment}
                options={assignmentTypeOptions}
                selectedAssignmentId={selectedAssignment?.id ?? null}
                statusValue={assignmentStatusFilter}
                totalCount={totalAssignmentCount}
                typeValue={assignmentTypeFilter}
                footerLabel={feed.error ?? undefined}
                hasMore={!isDemo && feed.hasMore}
                isLoadingMore={feed.isLoadingMore}
                onLoadMore={feed.loadMore}
                onStatusChange={(value) => {
                  setAssignmentStatusFilter(value);
                  syncAssignmentsIndexUrl(value, assignmentTypeFilter, assignmentDeskView, true);
                }}
                onTypeChange={(value) => {
                  setAssignmentTypeFilter(value);
                  syncAssignmentsIndexUrl(assignmentStatusFilter, value, assignmentDeskView, true);
                }}
              />
            )}
          </section>
        )}
        onCloseDetail={() => {
          setIsAssignmentDetailOpen(false);
          syncAssignmentsIndexUrl(assignmentStatusFilter, assignmentTypeFilter, assignmentDeskView, true);
        }}
        detail={selectedAssignment ? (
          <AssignmentRow
            assignment={selectedAssignment}
            disabled={disabled}
            graph={graph}
            messages={messages}
            note={assignmentActionNote}
            onNoteChange={setAssignmentActionNote}
            reportingDecision={selectedReportingDecision}
            reportingMergeTargetItemId={reportingMergeTargetItemId}
            onReportingMergeTargetItemIdChange={setReportingMergeTargetItemId}
            knowledgeQuery={assignmentKnowledgeQuery}
          />
        ) : (
          <section className="category-steering-section">
            <SectionHeader title="Assignment Detail" detail="No assignment selected" />
            <EmptyRow label="Select an assignment to inspect work details." />
          </section>
        )}
      />
      {isCreateAssignmentOpen ? (
        <div
          className="news-desk-modal"
          data-news-desk-assignment-create-modal
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setIsCreateAssignmentOpen(false);
          }}
        >
          <div className="news-desk-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="assignment-create-title">
            <header className="news-desk-modal__header">
              <div>
                <p className="story-label">Assignment Dispatch</p>
                <h3 id="assignment-create-title">Create Assignment</h3>
                <span>Analysis and re-index work</span>
              </div>
              <button type="button" onClick={() => setIsCreateAssignmentOpen(false)}>Close</button>
            </header>
            <AssignmentCreationPanel
              actionState={actionState}
              analysisProfiles={analysisProfiles}
              corpora={corpora}
              disabled={disabled}
              onClose={() => setIsCreateAssignmentOpen(false)}
              onCreateAssignment={onCreateAnalysisReindexAssignment}
              onSubmitted={() => setIsCreateAssignmentOpen(false)}
            />
          </div>
        </div>
      ) : null}
      {assignmentKnowledgeQuery.dialog}
    </>
  );
}

function AssignmentManagementGrid({
  assignmentEvents,
  assignments,
  metrics,
  onSelect,
  onStatusChange,
  onTypeChange,
  onLoadMore,
  options,
  selectedAssignmentId,
  statusValue,
  totalCount,
  typeValue,
  footerLabel,
  hasMore,
  isLoadingMore,
}: {
  assignmentEvents: AssignmentEventRecord[];
  assignments: AssignmentRecord[];
  metrics: AssignmentMetrics;
  onSelect: (assignmentId: string) => void;
  onStatusChange: (value: string) => void;
  onTypeChange: (value: string) => void;
  onLoadMore?: () => void;
  options: AssignmentTypeOption[];
  selectedAssignmentId?: string | null;
  statusValue: string;
  totalCount: number;
  typeValue: string;
  footerLabel?: string | null;
  hasMore?: boolean;
  isLoadingMore?: boolean;
}) {
  const statusFilters = [
    { key: "", label: "All", count: metrics.total },
    { key: "open", label: "Open", count: metrics.open },
    { key: "claimed", label: "Claimed", count: metrics.claimed },
    { key: "completed", label: "Completed", count: metrics.completed },
    { key: "canceled", label: "Canceled", count: metrics.canceled },
  ];
  const cards = assignments.map((assignment, index) => assignmentToNewsroomCard(assignment, index, latestReportingPacketDecisionForAssignment(assignmentEvents, assignment.id)));
  return (
    <NewsroomCardGrid
      cards={cards}
      emptyLabel="No assignments found"
      filterLabel="Assignment type"
      filterOptions={[
        { key: "", label: "All assignment types", count: totalCount },
        ...options.map((option) => ({ key: option.key, label: option.label, count: option.count })),
      ]}
      filterValue={typeValue}
      footerLabel={footerLabel}
      hasMore={hasMore}
      isLoadingMore={isLoadingMore}
      metricValue={statusValue}
      metrics={statusFilters}
      onFilterChange={onTypeChange}
      onLoadMore={onLoadMore}
      onMetricChange={onStatusChange}
      onSelect={onSelect}
      selectedId={selectedAssignmentId}
    />
  );
}

function ReportingStoryBudgetBoard({
  budget,
  disabled,
  onReview,
  onSelect,
  selectedAssignmentId,
}: {
  budget: ReturnType<typeof buildReportingStoryBudget>;
  disabled: boolean;
  onReview: (candidate: ReportingStoryBudgetCandidate, decision: ReportingPacketReviewDecision) => void;
  onSelect: (assignmentId: string) => void;
  selectedAssignmentId?: string | null;
}) {
  const totals = budget.totals;
  return (
    <div className="news-desk-story-budget" data-reporting-story-budget>
      <header className="news-desk-story-budget__summary">
        <div>
          <p className="story-label">Coverage Theme Story Budget</p>
          <h3>{totals.slotCount} slots / {totals.dispatchedCount} candidates</h3>
          <span>{formatBudgetState(totals.state, totals.delta)} / {formatCoverageThemePhase(totals.phase)}</span>
        </div>
        <div className="news-desk-story-budget__metrics" aria-label="Reporting story budget totals">
          <span data-story-budget-total="phase">{formatCoverageThemePhase(totals.phase)}</span>
          <span data-story-budget-total="filled-slots">{totals.filledSlotCount} filled slots</span>
          <span data-story-budget-total="unresolved-slots">{totals.unresolvedSlotCount} unresolved slots</span>
          <span data-story-budget-total="research-packets">{totals.researchPacketCount} research packets</span>
          <span data-story-budget-total="reporting-packets">{totals.reportingPacketCount} reporting packets</span>
          <span data-story-budget-total="selected">{totals.selectedCount} selected</span>
          <span data-story-budget-total="briefed">{totals.briefedCount} briefed</span>
          <span data-story-budget-total="merged">{totals.mergedCount} merged</span>
          <span data-story-budget-total="held">{totals.heldCount} held</span>
          <span data-story-budget-total="killed">{totals.killedCount} killed</span>
          <span data-story-budget-total="undecided">{totals.undecidedCount} undecided</span>
          <span data-story-budget-total="copywriting">{totals.copywritingAssignmentCount} copywriting</span>
          <span data-story-budget-total="drafts">{totals.draftItemCount} drafts</span>
          {totals.degradedCount ? <span data-story-budget-total="degraded">{totals.degradedCount} degraded</span> : null}
        </div>
      </header>
      {budget.sections.length ? budget.sections.map((section) => (
        <ReportingStoryBudgetSectionView
          disabled={disabled}
          key={`${section.editionId}-${section.key}`}
          onReview={onReview}
          onSelect={onSelect}
          section={section}
          selectedAssignmentId={selectedAssignmentId}
        />
      )) : <EmptyRow label="No reporting edition-candidate assignments found" />}
    </div>
  );
}

function ReportingStoryBudgetSectionView({
  disabled,
  onReview,
  onSelect,
  section,
  selectedAssignmentId,
}: {
  disabled: boolean;
  onReview: (candidate: ReportingStoryBudgetCandidate, decision: ReportingPacketReviewDecision) => void;
  onSelect: (assignmentId: string) => void;
  section: ReportingStoryBudgetSection;
  selectedAssignmentId?: string | null;
}) {
  return (
    <section
      className="news-desk-story-budget-section"
      data-story-budget-section={section.key}
      data-story-budget-edition={section.editionId}
      data-story-budget-state={section.state}
    >
      <header className="news-desk-story-budget-section__header">
        <div>
          <p className="story-label">{section.editionLabel}</p>
          <h4>{section.title}</h4>
          <span>{formatBudgetState(section.state, section.delta)} / {formatCoverageThemePhase(section.phase)}</span>
        </div>
        <div className="news-desk-story-budget__metrics">
          <span data-story-budget-metric="phase">{formatCoverageThemePhase(section.phase)}</span>
          <span data-story-budget-metric="slots">{section.slotCount} slots</span>
          <span data-story-budget-metric="filled-slots">{section.filledSlotCount} filled slots</span>
          <span data-story-budget-metric="unresolved-slots">{section.unresolvedSlotCount} unresolved slots</span>
          <span data-story-budget-metric="dispatched">{section.dispatchedCount} dispatched</span>
          <span data-story-budget-metric="research-packets">{section.researchPacketCount} research packets</span>
          <span data-story-budget-metric="reporting-packets">{section.reportingPacketCount} reporting packets</span>
          <span data-story-budget-metric="selected">{section.selectedCount} selected</span>
          <span data-story-budget-metric="briefed">{section.briefedCount} briefed</span>
          <span data-story-budget-metric="undecided">{section.undecidedCount} undecided</span>
          <span data-story-budget-metric="copywriting">{section.copywritingAssignmentCount} copywriting</span>
          <span data-story-budget-metric="drafts">{section.draftItemCount} drafts</span>
          {section.degradedCount ? <span data-story-budget-metric="degraded">{section.degradedCount} degraded</span> : null}
        </div>
      </header>
      <div className="news-desk-story-budget-candidates">
        {section.slots.map((slot) => (
          <ReportingStoryBudgetSlotView
            disabled={disabled}
            key={slot.slotId}
            onReview={onReview}
            onSelect={onSelect}
            selectedAssignmentId={selectedAssignmentId}
            slot={slot}
          />
        ))}
      </div>
    </section>
  );
}

function ReportingStoryBudgetSlotView({
  disabled,
  onReview,
  onSelect,
  selectedAssignmentId,
  slot,
}: {
  disabled: boolean;
  onReview: (candidate: ReportingStoryBudgetCandidate, decision: ReportingPacketReviewDecision) => void;
  onSelect: (assignmentId: string) => void;
  selectedAssignmentId?: string | null;
  slot: ReportingStoryBudgetSlot;
}) {
  return (
    <section
      className="news-desk-story-budget-slot"
      data-story-budget-slot={slot.slotId}
      data-story-budget-slot-status={slot.status}
    >
      <header className="news-desk-story-budget-slot__header">
        <strong>Slot {slot.slotRank ?? "?"}</strong>
        <span>{slot.targetType}{slot.targetLengthBand ? ` / ${slot.targetLengthBand}` : ""}</span>
        <span>{slot.candidateCount} candidates</span>
        <span>{slot.filled ? "filled" : "open"}</span>
      </header>
      {slot.candidates.length ? slot.candidates.map((candidate) => (
        <ReportingStoryBudgetCandidateRow
          candidate={candidate}
          disabled={disabled}
          key={candidate.assignmentId}
          onReview={onReview}
          onSelect={onSelect}
          selected={selectedAssignmentId === candidate.assignmentId}
        />
      )) : (
        <p className="news-desk-story-budget-slot__empty">No reporting candidates assigned to this slot yet.</p>
      )}
    </section>
  );
}

function ReportingStoryBudgetCandidateRow({
  candidate,
  disabled,
  onReview,
  onSelect,
  selected,
}: {
  candidate: ReportingStoryBudgetCandidate;
  disabled: boolean;
  onReview: (candidate: ReportingStoryBudgetCandidate, decision: ReportingPacketReviewDecision) => void;
  onSelect: (assignmentId: string) => void;
  selected: boolean;
}) {
  const decisionLabel = candidate.decision ? formatReportingPacketDecision(candidate.decision) : "Undecided";
  const recommendationDecision = normalizeReportingPacketDecision(candidate.editorRecommendation);
  return (
    <article
      className="news-desk-story-budget-candidate"
      data-selected={selected || undefined}
      data-story-budget-candidate={candidate.assignmentId}
      data-reporting-decision={candidate.decision ?? ""}
      data-reporting-packet={candidate.hasReportingPacket ? "true" : "false"}
    >
      <button
        type="button"
        className="news-desk-story-budget-candidate__main"
        onClick={() => onSelect(candidate.assignmentId)}
      >
        <span>{candidate.candidateRank ? `Candidate ${candidate.candidateRank}` : candidate.sectionKey}</span>
        <strong>{candidate.title}</strong>
        <em>{candidate.hasReportingPacket ? candidate.summary ?? "Reporting packet available" : "No reporting packet yet"}</em>
      </button>
      <div className="news-desk-story-budget-candidate__packet">
        <span data-story-budget-recommendation={candidate.editorRecommendation ?? "none"}>
          {recommendationDecision ? `Recommend ${formatReportingPacketDecision(recommendationDecision)}` : "No recommendation"}
        </span>
        <span data-story-budget-decision-label>{decisionLabel}</span>
        {candidate.recommendedAngle ? <p><span>Angle</span>{candidate.recommendedAngle}</p> : null}
        {candidate.riskFlags.length ? <p><span>Risks</span>{candidate.riskFlags.slice(0, 2).join(" / ")}</p> : null}
        {candidate.coverageGaps.length ? <p><span>Gaps</span>{candidate.coverageGaps.slice(0, 2).join(" / ")}</p> : null}
        {candidate.openQuestions.length ? <p><span>Questions</span>{candidate.openQuestions.slice(0, 2).join(" / ")}</p> : null}
        <div className="news-desk-story-budget-candidate__counts">
          <span>{candidate.acceptedReferenceCount} accepted refs</span>
          <span>{candidate.proposedReferenceCount} prospects</span>
          <span>{candidate.researchPacketCount} research packets</span>
        </div>
        {candidate.degraded ? (
          <p data-story-budget-degraded="true"><span>Degraded</span>{candidate.fallbackReason ?? "agent fallback"}{candidate.agentExitStatus != null ? ` / exit ${candidate.agentExitStatus}` : ""}</p>
        ) : null}
        {candidate.copywritingAssignmentId ? (
          <p data-reporting-copywriting-assignment={candidate.copywritingAssignmentId}><span>Copywriting</span>{candidate.copywritingAssignmentId} / {candidate.copywritingStatus ?? "queued"}</p>
        ) : null}
        {candidate.draftItemId ? (
          <p data-reporting-draft-item={candidate.draftItemId}><span>Draft</span>{candidate.draftItemId} / not placed in an edition</p>
        ) : null}
        {candidate.targetItemId ? <p><span>Merge target</span>{candidate.targetItemId}</p> : null}
      </div>
      <div className="news-desk-story-budget-candidate__actions">
        {(["select", "brief", "hold", "kill"] as ReportingPacketReviewDecision[]).map((decision) => (
          <button
            type="button"
            data-story-budget-decision={decision}
            disabled={disabled || !candidate.hasReportingPacket}
            key={decision}
            onClick={() => onReview(candidate, decision)}
          >
            {decision === "select" ? "Select" : decision === "brief" ? "Brief" : decision === "hold" ? "Hold" : "Kill"}
          </button>
        ))}
      </div>
    </article>
  );
}

function formatBudgetState(state: "needs" | "full" | "over", delta: number): string {
  if (state === "full") return "full";
  if (state === "over") return `over by ${Math.abs(delta)}`;
  return `needs ${Math.abs(delta)} more`;
}

function formatCoverageThemePhase(phase: ReportingStoryBudgetPhase): string {
  if (phase === "plan") return "Plan";
  if (phase === "research") return "Research";
  if (phase === "reporting") return "Reporting";
  if (phase === "review") return "Review";
  if (phase === "copywriting") return "Copywriting";
  return "Draft";
}

function AssignmentRow({
  assignment,
  disabled,
  graph,
  knowledgeQuery,
  messages,
  note,
  onNoteChange,
  onReportingMergeTargetItemIdChange,
  reportingDecision,
  reportingMergeTargetItemId,
}: {
  assignment: AssignmentRecord;
  disabled: boolean;
  graph: SemanticGraph;
  knowledgeQuery: KnowledgeQueryControl;
  messages: MessageRecord[];
  note: string;
  onNoteChange: (note: string) => void;
  onReportingMergeTargetItemIdChange: (value: string) => void;
  reportingDecision: ReportingPacketDecisionSummary | null;
  reportingMergeTargetItemId: string;
}) {
  const targets = graph.outgoing("assignment", assignment.id)
    .filter((relation) => relation.predicate === "requests_work_on")
    .map((relation) => graph.resolveRelationObject(relation, "outgoing"))
    .filter((target): target is SemanticObjectSummary => Boolean(target));
  const context = assignmentContextMetadata(assignment);
  const analysisPlan = assignmentAnalysisReindexMetadata(assignment);
  const researchPackets = researchPacketsForAssignment(assignment, graph, messages);
  const reportingPackets = researchPackets.filter((packet) => packet.kind === "reporting_context_packet");
  const terminal = assignment.status === "completed" || assignment.status === "canceled";

  return (
    <article
      className={`news-desk-assignment-row${terminal ? " news-desk-assignment-row--terminal" : ""}`}
      data-assignment-candidate={assignment.id}
      data-assignment-id={assignment.id}
      data-assignment-status={assignment.status}
      data-reporting-decision={reportingDecision?.decision}
    >
      <div className="news-desk-assignment-row__main">
        <header className="news-desk-assignment-row__title">
          <div>
            <h4>{assignment.title}</h4>
            <p className="news-desk-assignment-row__title-meta">
              <StatusPill status={assignment.status} />
              <span>{assignment.assignmentTypeKey}</span>
            </p>
          </div>
        </header>
        <KnowledgeQueryStatus error={knowledgeQuery.error} loading={knowledgeQuery.loading} />
        {knowledgeQuery.result ? (
          <KnowledgeQueryResultBlock result={knowledgeQuery.result} onClear={knowledgeQuery.clear} />
        ) : (
          <>
            <p>{assignment.summary ?? "Detailed assignment brief is stored as a private S3 payload attachment."}</p>
            {context ? (
              <>
                <p className="news-desk-assignment-row__angle">
                  <span>{context.deskTitle ?? context.deskKey ?? "Desk"}</span>
                  {`${context.focusTitle ?? context.focusKey ?? "focus"} / ${context.targetSystemType ?? context.contextProfile ?? "context"}`}
                </p>
                {context.contextProfile || context.contextTokenBudget ? (
                  <p className="news-desk-assignment-row__angle">
                    <span>Context</span>
                    {[context.contextProfile, context.contextTokenBudget ? `${context.contextTokenBudget} tokens` : null].filter(Boolean).join(" / ")}
                  </p>
                ) : null}
                {context.expectedEvidenceClasses.length ? (
                  <p className="news-desk-assignment-row__angle">
                    <span>Evidence</span>
                    {context.expectedEvidenceClasses.slice(0, 2).join(" / ")}
                  </p>
                ) : null}
                {context.comparisonQuestions.length ? (
                  <p className="news-desk-assignment-row__angle">
                    <span>Compare</span>
                    {context.comparisonQuestions.slice(0, 2).join(" / ")}
                  </p>
                ) : null}
              </>
            ) : null}
            {assignment.instructions ? (
              <p className="news-desk-assignment-row__angle">
                <span>Instructions</span>
                {assignment.instructions}
              </p>
            ) : null}
            {analysisPlan ? (
              <div className="news-desk-assignment-row__packets">
                <p className="news-desk-assignment-row__angle">
                  <span>Analysis plan</span>
                  {`${analysisPlan.profileTitle} / ${analysisPlan.mode} / ${analysisPlan.corpusKey}`}
                </p>
                {analysisPlan.commandLines.slice(0, 2).map((commandLine) => (
                  <pre className="news-desk-analysis-command" key={commandLine}>{commandLine}</pre>
                ))}
                <p className="news-desk-assignment-row__angle">
                  <span>Destructive preview</span>
                  {analysisPlan.destructiveSummary}
                </p>
              </div>
            ) : null}
            {researchPackets.length ? (
              <div className="news-desk-assignment-row__packets">
                {researchPackets.slice(0, 2).map((packet) => (
                  <p className="news-desk-assignment-row__angle" key={packet.id}>
                    <span>{packet.label}</span>
                    {`${packet.summary}${packet.proposedReferenceCount ? ` / ${packet.proposedReferenceCount} proposed refs` : ""}${packet.queryCount ? ` / ${packet.queryCount} queries` : ""}${packet.sourceDomains.length ? ` / ${packet.sourceDomains.slice(0, 2).join(", ")}` : ""}`}
                  </p>
                ))}
              </div>
            ) : null}
            {reportingPackets.length ? (
              <div className="news-desk-assignment-row__packets" data-reporting-packet-review>
                <p className="news-desk-assignment-row__angle">
                  <span>Editorial decision</span>
                  {reportingDecision ? `${formatReportingPacketDecision(reportingDecision.decision)} / ${reportingDecision.note ?? "no note"}` : "No editor decision yet"}
                </p>
                {reportingDecision?.copywritingAssignmentId ? (
                  <p className="news-desk-assignment-row__angle" data-reporting-copywriting-assignment={reportingDecision.copywritingAssignmentId}>
                    <span>Copywriting Assignment</span>
                    {`${reportingDecision.copywritingAssignmentId} / ${reportingDecision.copywritingStatus ?? "queued"}`}
                  </p>
                ) : null}
                {reportingDecision?.draftItemId ? (
                  <p className="news-desk-assignment-row__angle" data-reporting-draft-item={reportingDecision.draftItemId}>
                    <span>Draft Item</span>
                    {`${reportingDecision.draftItemId} / not placed in an edition`}
                  </p>
                ) : null}
                <label>
                  <span>Merge target Item ID</span>
                  <input
                    data-reporting-merge-target={assignment.id}
                    disabled={disabled}
                    value={reportingMergeTargetItemId}
                    onChange={(event) => onReportingMergeTargetItemIdChange(event.target.value)}
                    placeholder="Required only for Merge Packet"
                  />
                </label>
              </div>
            ) : null}
            <div className="news-desk-assignment-row__meta">
              <span>{assignment.queueKey}</span>
              <span>{assignment.assigneeKey ?? "unassigned"}</span>
              <span>{targets.length ? targets.map((target) => target.label).join(" / ") : "no linked targets"}</span>
            </div>
          </>
        )}
      </div>
      <div className="news-desk-assignment-row__actions">
        <label>
          <span>Note</span>
          <textarea
            data-assignment-reason={assignment.id}
            disabled={disabled}
            rows={2}
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
          />
        </label>
      </div>
    </article>
  );
}

function normalizeAnalysisReindexMode(value: string | null | undefined): AnalysisReindexMode {
  return ANALYSIS_REINDEX_MODES.includes(value as AnalysisReindexMode) ? value as AnalysisReindexMode : "online-update";
}

function formatAnalysisReindexModeLabel(mode: AnalysisReindexMode): string {
  if (mode === "online-update") return "Online update - new or changed accepted references";
  if (mode === "classifier-retrain") return "Classifier retrain - rebuild topic classifier";
  if (mode === "scoped-topic-rebuild") return "Scoped topic rebuild - one desk or focus";
  if (mode === "entity-graph-rebuild") return "Entity graph rebuild - generated graph outputs";
  return "Generated analysis rebuild - clear and rebuild targeted generated outputs";
}

function formatAnalysisCorpusLabel(corpusKey: string, corpora: CategorySteeringCorpus[]): string {
  const corpusId = knowledgeCorpusIdFromKey(corpusKey);
  const corpus = corpora.find((entry) => entry.id === corpusId || entry.id === corpusKey || entry.name === corpusKey);
  return corpus?.name && corpus.name !== corpusKey ? `${corpusKey} - ${corpus.name}` : corpusKey;
}

function analysisCorpusKeyFromRecord(corpus: CategorySteeringCorpus): string | null {
  if (corpus.name && !corpus.name.startsWith("knowledge-corpus-")) return corpus.name;
  if (!corpus.id) return null;
  return corpus.id.replace(/^knowledge-corpus-/, "");
}

function mergeAnalysisCorpora(configuredCorpora: CategorySteeringCorpus[], liveCorpora: CategorySteeringCorpus[]): CategorySteeringCorpus[] {
  const byKey = new Map<string, CategorySteeringCorpus>();
  for (const corpus of [...configuredCorpora, ...liveCorpora]) {
    const key = analysisCorpusKeyFromRecord(corpus);
    if (!key) continue;
    byKey.set(key, { ...byKey.get(key), ...corpus });
  }
  return Array.from(byKey.values());
}

function analysisReindexModeHelp(mode: AnalysisReindexMode): string {
  if (mode === "generated-analysis-rebuild") return "Use this for a full generated-output rebuild for the selected profile. It still creates an assignment only; the worker/operator executes it later.";
  if (mode === "classifier-retrain") return "Use this when authoritative labels or accepted references should retrain the semi-supervised topic classifier.";
  if (mode === "scoped-topic-rebuild") return "Use this when proposals for a desk or focus topic should be regenerated from the accepted taxonomy plus steering feedback.";
  if (mode === "entity-graph-rebuild") return "Use this when generated ontology/entity graph records should be rebuilt from accepted references.";
  return "Use this for incremental processing of new or changed accepted references without clearing broader generated outputs.";
}

function parseAnalysisOverrideJson(
  text: string,
  profile: AnalysisProfileSummary | null,
): { value: Record<string, unknown>; error: string | null } {
  if (!profile) return { value: {}, error: null };
  if (!text.trim()) return { value: {}, error: null };
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: {}, error: "Overrides must be a JSON object." };
    }
    const value = parsed as Record<string, unknown>;
    const unsafeKey = Object.keys(value).find((key) => !profile.allowedOverrides.includes(key));
    if (unsafeKey) return { value: {}, error: `${unsafeKey} is not allowed for ${profile.key}.` };
    return { value, error: null };
  } catch (error) {
    return { value: {}, error: error instanceof Error ? error.message : "Overrides JSON is invalid." };
  }
}

function buildUiAnalysisReindexAssignmentPlan({
  actorLabel,
  categorySet,
  corpora,
  draft,
  now,
  profile,
}: {
  actorLabel: string;
  categorySet: CategorySteeringCategorySet | null;
  corpora: CategorySteeringCorpus[];
  draft: AnalysisReindexDraft;
  now: string;
  profile: AnalysisProfileSummary;
}): {
  assignment: AssignmentRecord;
  event: AssignmentEventRecord;
  relation: SemanticRelationRecord | null;
  metadata: Record<string, unknown>;
} {
  const corpusKey = draft.corpusKey.trim() || profile.corpusKey || "unknown";
  const corpusId = resolveUiKnowledgeCorpusId(corpora, corpusKey);
  const classifierId = profile.classifierId ?? `${safeUiId(corpusKey)}-classifier`;
  const effectiveParameters = { ...profile.defaults, ...draft.overrides };
  const planRunId = `analysis-reindex-${safeUiId(profile.key)}-${safeUiId(corpusKey)}-${hashUiKey([draft.mode, stableStringify(draft.overrides)])}`;
  const assignmentId = `assignment-analysis-reindex-${safeUiId(corpusKey)}-${safeUiId(profile.key)}-${hashUiKey([draft.mode, stableStringify(draft.overrides)])}`;
  const queueKey = `analysis:reindex:${safeUiId(corpusKey)}:${profile.scope}`;
  const commandPlan = buildAnalysisCommandPlanPreview({ profile, corpusKey, mode: draft.mode, overrides: draft.overrides });
  const destructivePlan = buildAnalysisDestructivePreview({ profile, corpusKey, mode: draft.mode });
  const metadata = {
    kind: "analysis.reindex.requested",
    analysisProfileKey: profile.key,
    analysisProfileTitle: profile.title,
    analysisScope: profile.scope,
    reindexMode: draft.mode,
    corpusKey,
    corpusId,
    classifierId,
    categorySetId: categorySet?.id ?? null,
    parameterOverrides: draft.overrides,
    effectiveParameters,
    commandPlan,
    destructivePlan,
    expectedOutputs: profile.expectedOutputs,
    planRunId,
    profilesPath: "corpora/papyrus-analysis-profiles.yml",
    createdFrom: "newsroom/assignments",
  };
  const assignment: AssignmentRecord = {
    id: assignmentId,
    assignmentTypeKey: "analysis.reindex",
    queueKey,
    queueStatusKey: `${queueKey}#open`,
    status: "open",
    priority: 40,
    title: `Re-index ${profile.title}`,
    brief: `Prepare ${draft.mode} for ${corpusKey} using ${profile.key}.`,
    instructions: "Inspect this command plan and destructive preview before running Biblicus. Creating this assignment does not execute analysis or cleanup.",
    assigneeType: null,
    assigneeId: null,
    assigneeKey: null,
    claimedAt: null,
    claimExpiresAt: null,
    completedAt: null,
    canceledAt: null,
    corpusId,
    categorySetId: categorySet?.id ?? null,
    classifierId,
    sourceSnapshotId: normalizeMetadataString(effectiveParameters.extractionSnapshot) ?? null,
    importRunId: null,
    createdBy: actorLabel,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "assignments",
    metadata,
  };
  const event: AssignmentEventRecord = {
    id: `assignment-event-${assignmentId}-created`,
    assignmentId,
    assignmentTypeKey: assignment.assignmentTypeKey,
    queueKey,
    eventType: "created",
    fromStatus: null,
    toStatus: "open",
    actorSub: null,
    actorLabel,
    note: "Created re-index assignment from analysis profile.",
    createdAt: now,
    metadata: {
      kind: "analysis.reindex.assignment_created",
      analysisProfileKey: profile.key,
      reindexMode: draft.mode,
      corpusKey,
      commandCount: commandPlan.length,
    },
  };
  const relation = categorySet ? buildUiAnalysisTargetRelation({
    assignment,
    categorySet,
    classifierId,
    corpusKey,
    now,
    profile,
    mode: draft.mode,
  }) : null;
  return { assignment, event, relation, metadata };
}

function insightTargetForReference(reference: ReferenceRecord): InsightTarget {
  return {
    kind: "reference",
    id: reference.id,
    lineageId: reference.lineageId ?? reference.id,
    title: reference.title ?? reference.externalItemId,
    subtitle: reference.corpusId,
    versionNumber: reference.versionNumber ?? null,
  };
}

function insightTargetForNewsroomSection(section: NewsroomSectionRecord): InsightTarget {
  return {
    kind: "newsroomSection",
    id: section.id,
    lineageId: section.id,
    title: section.title,
    subtitle: section.type,
    versionNumber: null,
  };
}

function insightTargetForSemanticObject(object: SemanticObjectSummary): InsightTarget | null {
  if (object.kind !== "category" && object.kind !== "semanticNode") return null;
  return {
    kind: object.kind,
    id: object.id,
    lineageId: object.lineageId,
    title: object.label,
    subtitle: object.subtitle,
    versionNumber: object.versionNumber ?? null,
  };
}

function insightTargetKey(target: InsightTarget): string {
  return `${target.kind}#${target.lineageId}`;
}

function buildUiInsightRelation(message: MessageRecord, target: InsightTarget, now: string): SemanticRelationRecord {
  const subjectStateKey = semanticStateKey("message", message.id);
  const objectStateKey = semanticStateKey(target.kind, target.lineageId);
  const subjectVersionKey = semanticVersionKey("message", message.id);
  const objectVersionKey = semanticVersionKey(target.kind, target.id);
  return {
    id: `semantic-relation-${hashUiKey([subjectVersionKey, "insight_about", objectVersionKey])}`,
    relationState: "current",
    predicate: "insight_about",
    relationTypeId: "semantic-relation-type-insight-about",
    relationTypeKey: "insight_about",
    relationDomain: "knowledge",
    subjectKind: "message",
    subjectId: message.id,
    subjectLineageId: message.id,
    subjectVersionNumber: 1,
    objectKind: target.kind,
    objectId: target.id,
    objectLineageId: target.lineageId,
    objectVersionNumber: target.versionNumber ?? null,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#message`,
    predicateObjectStateKey: `insight_about#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: null,
    confidence: null,
    rank: 1,
    classifierId: null,
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: null,
    importRunId: null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: {
      targetTitle: target.title,
      targetSubtitle: target.subtitle ?? null,
    },
  };
}

function buildUiAnalysisTargetRelation({
  assignment,
  categorySet,
  classifierId,
  corpusKey,
  now,
  profile,
  mode,
}: {
  assignment: AssignmentRecord;
  categorySet: CategorySteeringCategorySet;
  classifierId: string;
  corpusKey: string;
  now: string;
  profile: AnalysisProfileSummary;
  mode: AnalysisReindexMode;
}): SemanticRelationRecord {
  const subjectStateKey = semanticStateKey("assignment", assignment.id);
  const objectLineageId = categorySet.lineageId ?? categorySet.id;
  const objectStateKey = semanticStateKey("categorySet", objectLineageId);
  const subjectVersionKey = semanticVersionKey("assignment", assignment.id);
  const objectVersionKey = semanticVersionKey("categorySet", categorySet.id);
  return {
    id: `semantic-relation-${hashUiKey([subjectVersionKey, "requests_work_on", objectVersionKey, profile.key])}`,
    relationState: "current",
    predicate: "requests_work_on",
    relationTypeId: "semantic-relation-type-requests-work-on",
    relationTypeKey: "requests_work_on",
    relationDomain: "workflow",
    subjectKind: "assignment",
    subjectId: assignment.id,
    subjectLineageId: assignment.id,
    subjectVersionNumber: null,
    objectKind: "categorySet",
    objectId: categorySet.id,
    objectLineageId,
    objectVersionNumber: categorySet.versionNumber ?? null,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#assignment`,
    predicateObjectStateKey: `requests_work_on#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: null,
    confidence: null,
    rank: 1,
    classifierId,
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: null,
    importRunId: null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: {
      analysisProfileKey: profile.key,
      reindexMode: mode,
      corpusKey,
    },
  };
}

function buildUiAuthoritativeLabelRelation(
  reference: ReferenceRecord,
  category: CategorySteeringCategory,
  actorLabel: string,
  note: string | null,
  now: string,
  sourceRelationId: string | null,
): SemanticRelationRecord {
  const subjectLineageId = reference.lineageId ?? reference.id;
  const objectLineageId = category.lineageId ?? category.id;
  const subjectStateKey = semanticStateKey("reference", subjectLineageId);
  const objectStateKey = semanticStateKey("category", objectLineageId);
  const subjectVersionKey = semanticVersionKey("reference", reference.id);
  const objectVersionKey = semanticVersionKey("category", category.id);
  return {
    id: `semantic-relation-${hashUiKey([subjectStateKey, "authoritative_label", objectStateKey])}`,
    relationState: "current",
    predicate: "authoritative_label",
    relationTypeId: "semantic-relation-type-authoritative-label",
    relationTypeKey: "authoritative_label",
    relationDomain: "taxonomy",
    subjectKind: "reference",
    subjectId: reference.id,
    subjectLineageId,
    subjectVersionNumber: reference.versionNumber ?? null,
    objectKind: "category",
    objectId: category.id,
    objectLineageId,
    objectVersionNumber: category.versionNumber ?? null,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#reference`,
    predicateObjectStateKey: `authoritative_label#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: 1,
    confidence: null,
    rank: 1,
    classifierId: null,
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: null,
    importRunId: null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: {
      kind: sourceRelationId ? "classification.authoritative_label.accepted_from_prediction" : "classification.authoritative_label.manual",
      actor: actorLabel,
      note,
      sourceMode: sourceRelationId ? "accepted_prediction" : "manual",
      sourcePredictionId: sourceRelationId,
    },
  };
}

function buildAnalysisCommandPlanPreview({
  profile,
  corpusKey,
  mode,
  overrides,
}: {
  profile: AnalysisProfileSummary;
  corpusKey: string;
  mode: AnalysisReindexMode;
  overrides: Record<string, unknown>;
}): AnalysisCommandPlanEntry[] {
  const corpusPath = `corpora/${corpusKey || profile.corpusKey || "unknown"}`;
  const effective = { ...profile.defaults, ...overrides };
  const extractionSnapshot = normalizeMetadataString(effective.extractionSnapshot) ?? "<extraction-snapshot>";
  const configurationName = normalizeMetadataString(effective["graph.configurationName"]) ?? profile.configurationName ?? profile.key;
  const configurations = profile.biblicus.configurations.flatMap((configuration) => ["--configuration", configuration]);
  if (profile.scope === "global-topic-model") {
    return [analysisCommand("topic-granularity-sweep", [
      "analyze", "topic-granularity-sweep",
      "--corpus", corpusPath,
      ...configurations,
      ...analysisOverrideArgs(effective, profile, new Set(["targetTopicRange", "extractionSnapshot"])),
      "--configuration-name", configurationName,
      "--extraction-snapshot", extractionSnapshot,
      "--target-topic-range", normalizeMetadataString(effective.targetTopicRange) ?? "10:20",
      "--format", "json",
    ], mode)];
  }
  if (profile.scope === "topic-classifier-train") {
    return [analysisCommand("topic-classifier-train", [
      "topic-classifier", "train",
      "--corpus", corpusPath,
      "--manifest", normalizeMetadataString(effective.seedManifestPath) ?? `${corpusPath}/metadata/topic-classifiers/${profile.classifierId ?? "classifier"}/seed-manifest.json`,
      ...configurations,
      ...analysisOverrideArgs(effective, profile, new Set(["seedManifestPath", "extractionSnapshot"])),
      "--configuration-name", configurationName,
      "--extraction-snapshot", extractionSnapshot,
    ], mode)];
  }
  if (profile.scope === "scoped-topic-model") {
    const steeringFeedbackPath = normalizeMetadataString(effective.steeringFeedbackPath);
    return [analysisCommand("taxonomy-discover", [
      "taxonomy", "discover",
      "--corpus", corpusPath,
      "--classifier", profile.classifierId ?? "classifier",
      "--extraction-snapshot", extractionSnapshot,
      ...(steeringFeedbackPath ? ["--steering-feedback", steeringFeedbackPath] : []),
      "--format", "json",
    ], mode)];
  }
  if (profile.scope === "topic-projection") {
    const authorityCorpusKey = normalizeMetadataString(effective.authorityCorpusKey) ?? "authority-corpus";
    return [analysisCommand("topic-classifier-project", [
      "topic-classifier", "project",
      "--classifier-corpus", `corpora/${authorityCorpusKey}`,
      "--target-corpus", corpusPath,
      "--classifier", profile.classifierId ?? "classifier",
      "--extraction-snapshot", extractionSnapshot,
      "--all",
      "--top-k", String(effective.topK ?? 5),
      "--review-threshold", String(effective.reviewThreshold ?? 0.35),
      "--format", "json",
    ], mode)];
  }
  if (profile.scope === "entity-graph") {
    const extractor = normalizeMetadataString(effective["graph.extractor"]) ?? profile.biblicus.extractor ?? "ner-entities";
    return [analysisCommand("graph-extract", [
      "graph", "extract",
      "--corpus", corpusPath,
      "--extractor", extractor,
      "--extraction-snapshot", extractionSnapshot,
      "--configuration-name", configurationName,
      ...configurations,
      ...analysisGraphOverrideArgs(effective, profile),
    ], mode)];
  }
  return [];
}

function buildAnalysisDestructivePreview({
  profile,
  corpusKey,
  mode,
}: {
  profile: AnalysisProfileSummary;
  corpusKey: string;
  mode: AnalysisReindexMode;
}): { executesNow: false; summary: string; mode: AnalysisReindexMode; profileKey: string; corpusKey: string } {
  const generatedOutput = profile.scope === "entity-graph"
    ? "generated semantic graph nodes and relations"
    : profile.scope === "scoped-topic-model"
      ? "new steering proposals for the selected scope"
      : "generated analysis projections tied to this profile/import run";
  return {
    executesNow: false,
    summary: `${mode} is assignment-only. A later worker may clear targeted ${generatedOutput}; accepted references, authoritative labels, category decisions, messages, and source files are preserved.`,
    mode,
    profileKey: profile.key,
    corpusKey,
  };
}

function analysisCommand(label: string, args: string[], mode: AnalysisReindexMode): AnalysisCommandPlanEntry {
  return {
    label,
    cwd: "/Users/ryan/Projects/Biblicus",
    executable: "uv",
    args: ["run", "--extra", "topic-modeling", "biblicus", ...args],
    metadata: { mode },
  };
}

function analysisOverrideArgs(effective: Record<string, unknown>, profile: AnalysisProfileSummary, exclude = new Set<string>()): string[] {
  return Object.entries(effective)
    .filter(([key]) => profile.allowedOverrides.includes(key) && !exclude.has(key) && !key.startsWith("graph."))
    .flatMap(([key, value]) => ["--override", `${key}=${formatAnalysisOverrideValue(value)}`]);
}

function analysisGraphOverrideArgs(effective: Record<string, unknown>, profile: AnalysisProfileSummary): string[] {
  const graphKeys = new Map([
    ["graph.model", "model"],
    ["graph.min_entity_length", "min_entity_length"],
    ["graph.max_entity_words", "max_entity_words"],
    ["graph.include_item_node", "include_item_node"],
    ["graph.window_size", "window_size"],
    ["graph.min_cooccurrence", "min_cooccurrence"],
  ]);
  return Object.entries(effective)
    .filter(([key]) => profile.allowedOverrides.includes(key) && graphKeys.has(key))
    .flatMap(([key, value]) => ["--override", `${graphKeys.get(key)}=${formatAnalysisOverrideValue(value)}`]);
}

function formatAnalysisOverrideValue(value: unknown): string {
  if (Array.isArray(value) || (value && typeof value === "object")) return JSON.stringify(value);
  return String(value);
}

function resolveUiKnowledgeCorpusId(corpora: CategorySteeringCorpus[], corpusKey: string): string {
  const expectedId = knowledgeCorpusIdFromKey(corpusKey);
  const corpus = corpora.find((entry) => entry.id === expectedId || entry.id === corpusKey || entry.name === corpusKey);
  return corpus?.id ?? expectedId;
}

function knowledgeCorpusIdFromKey(corpusKey: string): string {
  return `knowledge-corpus-${safeUiId(corpusKey)}`;
}

function safeUiId(value: unknown): string {
  return String(value ?? "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "unknown";
}

function semanticStateKey(kind: string, lineageId: string): string {
  return `${kind}#${lineageId}#current`;
}

function semanticVersionKey(kind: string, id: string): string {
  return `${kind}#${id}`;
}

function normalizeAdministrationPanel(value: string | null | undefined): AdministrationPanel {
  if (value === "policies" || value === "sections" || value === "procedures") return value;
  return "users";
}

function sortNewsroomSections(sections: NewsroomSectionRecord[]): NewsroomSectionRecord[] {
  return [...sections].sort((left, right) => {
    const typeDiff = (normalizeNewsroomSectionType(left.type) === "canonical" ? 0 : 1) - (normalizeNewsroomSectionType(right.type) === "canonical" ? 0 : 1);
    if (typeDiff !== 0) return typeDiff;
    const orderDiff = (left.sortOrder ?? 999999) - (right.sortOrder ?? 999999);
    if (orderDiff !== 0) return orderDiff;
    return left.title.localeCompare(right.title);
  });
}

function normalizeNewsroomSectionsWithFallback(
  sections: NewsroomSectionRecord[],
  fallbackSections: NewsroomSectionRecord[] = [],
): NewsroomSectionRecord[] {
  const fallbackById = new Map(fallbackSections.map((section) => [section.id, section]));
  return sortNewsroomSections(sections.map((section) => {
    const fallback = fallbackById.get(section.id);
    return {
      ...section,
      shortTitle: section.shortTitle?.trim() || fallback?.shortTitle || defaultNewsroomSectionShortTitle(section.id),
    };
  }));
}

function defaultNewsroomSectionShortTitle(sectionId: string): string {
  return NEWSROOM_SECTION_SHORT_TITLE_FALLBACKS[sectionId] ?? "";
}

function displayNewsroomSectionShortTitle(section: NewsroomSectionRecord): string {
  return section.shortTitle?.trim() || defaultNewsroomSectionShortTitle(section.id);
}

function normalizeNewsroomSectionType(value: string | null | undefined): "canonical" | "floating" {
  return value === "floating" || value === "rotating" ? "floating" : "canonical";
}

function isEnabledNewsroomSection(section: NewsroomSectionRecord): boolean {
  return section.enabled !== false && section.enabledStatus !== "disabled";
}

function formatNewsroomSectionTypeLabel(value: string | null | undefined): "Canonical" | "Rotating" {
  return normalizeNewsroomSectionType(value) === "canonical" ? "Canonical" : "Rotating";
}

function buildNewsroomSectionHref(sectionId: string, demo?: boolean): string {
  return getNewsDeskTabHref(`/newsroom/sections/${encodeURIComponent(sectionId)}`, demo);
}

function replaceNewsroomSection(sections: NewsroomSectionRecord[], section: NewsroomSectionRecord): NewsroomSectionRecord[] {
  return [...sections.filter((entry) => entry.id !== section.id), section];
}

function parseOptionalInt(value: string): number | null {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseCommaList(value: string): string[] {
  return value.split(",").map((entry) => entry.trim()).filter(Boolean);
}

function safeSectionId(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "section";
}

function isSectionDraftValid(draft: NewsroomSectionRecord): boolean {
  return Boolean(
    safeSectionId(draft.id)
    && draft.title.trim()
    && draft.shortTitle.trim()
    && draft.editorialMission.trim()
    && draft.editorialPolicy.trim(),
  );
}

function normalizeSectionDraft(draft: NewsroomSectionRecord, forUpdate: boolean): NewsroomSectionRecord | null {
  const id = safeSectionId(draft.id || draft.title);
  const title = draft.title.trim();
  const shortTitle = draft.shortTitle.trim();
  const editorialMission = draft.editorialMission.trim();
  const editorialPolicy = draft.editorialPolicy.trim();
  if (!id || !title || !shortTitle || !editorialMission || !editorialPolicy) return null;
  return {
    ...draft,
    id: forUpdate ? draft.id : id,
    title,
    shortTitle,
    type: draft.type === "floating" || draft.type === "rotating" ? "floating" : "canonical",
    editorialMission,
    editorialPolicy,
    enabled: Boolean(draft.enabled),
    enabledStatus: draft.enabled ? "enabled" : "disabled",
    defaultArticleTypes: (draft.defaultArticleTypes ?? []).map((entry) => (entry ?? "").trim()).filter(Boolean),
    defaultPageBudget: draft.defaultPageBudget ?? null,
    assignmentGuidance: draft.assignmentGuidance?.trim() || null,
    killCriteria: draft.killCriteria?.trim() || null,
    visualGuidance: draft.visualGuidance?.trim() || null,
  };
}

function createEmptyNewsroomSectionDraft(sortOrder: number): NewsroomSectionRecord {
  return {
    id: "",
    title: "",
    shortTitle: "",
    type: "canonical",
    editorialMission: "",
    editorialPolicy: "",
    enabled: true,
    enabledStatus: "enabled",
    sortOrder,
    defaultArticleTypes: [],
    defaultPageBudget: null,
    assignmentGuidance: null,
    killCriteria: null,
    visualGuidance: null,
  };
}

async function listNewsroomSectionsFromApi(dataClient: ReturnType<typeof generateClient<Schema>>): Promise<NewsroomSectionRecord[]> {
  if ("NewsroomSection" in dataClient.models) {
    const response = await dataClient.models.NewsroomSection.list({ authMode: USER_POOL_AUTH_MODE, limit: 500 });
    assertNoGraphQLErrors(response.errors);
    return ((response.data ?? []).filter(Boolean) as NewsroomSectionRecord[]);
  }
  const graphClient = dataClient as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{
      data?: {
        listNewsroomSections?: {
          items?: Array<NewsroomSectionRecord | null> | null;
          nextToken?: string | null;
        } | null;
      } | null;
      errors?: unknown[] | null;
    }>;
  };
  const query = `
    query ListNewsroomSections($limit: Int, $nextToken: String) {
      listNewsroomSections(limit: $limit, nextToken: $nextToken) {
        items {
          id
          title
          shortTitle
          type
          editorialMission
          editorialPolicy
          enabled
          enabledStatus
          sortOrder
          defaultArticleTypes
          defaultPageBudget
          assignmentGuidance
          killCriteria
          visualGuidance
          createdAt
          updatedAt
        }
        nextToken
      }
    }
  `;
  const rows: NewsroomSectionRecord[] = [];
  let nextToken: string | null | undefined = null;
  do {
    const response = await graphClient.graphql({
      query,
      variables: { limit: 500, nextToken },
      authMode: USER_POOL_AUTH_MODE,
    });
    assertNoGraphQLErrors(response.errors);
    const connection = response.data?.listNewsroomSections;
    rows.push(...((connection?.items ?? []).filter(Boolean) as NewsroomSectionRecord[]));
    nextToken = connection?.nextToken ?? null;
  } while (nextToken);
  return rows;
}

function compareDoctrineCategories(left: DoctrineCategory, right: DoctrineCategory): number {
  const depthDiff = (left.depth ?? 0) - (right.depth ?? 0);
  if (depthDiff !== 0) return depthDiff;
  const rankDiff = (left.rank ?? 999999) - (right.rank ?? 999999);
  if (rankDiff !== 0) return rankDiff;
  return left.displayName.localeCompare(right.displayName);
}

function formatDeskSectionHeadline(section: NewsDeskTab): string {
  if (section === "search") return "Search";
  if (section === "topics") return "Topics";
  if (section === "concepts") return "Concepts";
  if (section === "references") return "References";
  if (section === "insights") return "Insights";
  if (section === "messages") return "Messages";
  if (section === "assignments") return "Assignments";
  if (section === "administration") return "Administration";
  return "Newsroom";
}

function formatDeskSectionLede(section: NewsDeskTab): string {
  if (section === "search") return "Search the newsroom knowledge base with semantic and ontology context.";
  if (section === "topics") return "Review and shape the subject areas the newsroom covers.";
  if (section === "concepts") return "Browse people, organizations, places, and ideas found in the source material.";
  if (section === "references") return "Review source materials before they become usable evidence.";
  if (section === "insights") return "Browse recent research insights and discuss each one in a forum thread to refine the synthesis.";
  if (section === "messages") return "Read notes, rationales, forum threads, curation decisions, and other work products from people and agents.";
  if (section === "assignments") return "Create, filter, claim, and complete newsroom work.";
  if (section === "administration") return "Manage users, roles, doctrine, configurable newspaper sections, and newsroom procedures.";
  return "";
}

function topicTreeNodeToNewsroomCard(
  entry: {
    kind: "root" | "subcategory";
    node: CategorySteeringCategoryTreeNode;
    parentCategoryKey: string | null;
    proposalCount: number;
    referenceCount: number;
    subtopicCount: number | null;
  },
  index: number,
): NewsroomCardRecord {
  const title = entry.kind === "subcategory" ? `Subtopic: ${entry.node.displayName}` : entry.node.displayName;
  const subtitle = distinctNewsroomCardSubtitle(
    entry.node.displayName,
    entry.node.subtitle
      ?? entry.node.description
      ?? (entry.parentCategoryKey ? `Part of ${entry.parentCategoryKey}` : null),
  );
  const template = resolveNewsroomCardTemplate({
    bodyLength: subtitle?.length ?? 0,
    index,
    isUrgent: entry.proposalCount > 0 || entry.node.status === "proposed" || entry.node.status === "draft",
    mode: "desk",
    sectionKey: "topics",
    title,
    updatedAt: entry.node.updatedAt ?? entry.node.versionCreatedAt ?? null,
  });
  return {
    id: entry.node.categoryKey,
    ariaLabel: `Open topic ${entry.node.displayName}`,
    body: subtitle ? newsroomCardExcerpt(subtitle, 200) : null,
    dataAttributes: {
      "data-newsroom-card-topic-kind": entry.kind,
      "data-newsroom-card-topic-parent": entry.parentCategoryKey ?? undefined,
      "data-newsroom-card-topic-proposals": entry.proposalCount || undefined,
      "data-newsroom-card-topic-status": entry.node.status ?? "",
    },
    kicker: entry.kind === "subcategory" ? "Subtopic" : "Topic",
    meta: [
      entry.node.shortTitle ?? null,
      entry.subtopicCount !== null ? `${entry.subtopicCount} subtopics` : entry.parentCategoryKey ? `Parent ${entry.parentCategoryKey}` : null,
      `${entry.referenceCount} references`,
      entry.proposalCount > 0 ? `${entry.proposalCount} proposals` : null,
      entry.node.status ?? null,
    ].filter(Boolean),
    span: template.span,
    stamp: formatDateTime(entry.node.updatedAt ?? entry.node.versionCreatedAt ?? ""),
    templateRole: template.role,
    title,
  };
}

function semanticNodeToNewsroomCard(node: SemanticNodeRecord, index: number): NewsroomCardRecord {
  const lineageId = node.lineageId ?? node.id;
  const title = node.displayName ?? node.nodeKey;
  const subtitle = distinctNewsroomCardSubtitle(
    title,
    node.description
      ?? deriveDelimitedSubtitle(title)
      ?? null,
  );
  const template = resolveNewsroomCardTemplate({
    bodyLength: subtitle?.length ?? 0,
    index,
    isUrgent: node.status === "candidate" || node.status === "draft",
    mode: "desk",
    sectionKey: "concepts",
    title,
    updatedAt: node.updatedAt ?? node.createdAt ?? node.versionCreatedAt ?? null,
  });
  return {
    id: lineageId,
    ariaLabel: `Open concept ${title}`,
    body: subtitle ? newsroomCardExcerpt(subtitle, 220) : null,
    dataAttributes: {
      "data-newsroom-card-node-kind": node.nodeKind,
      "data-newsroom-card-node-status": node.status,
    },
    kicker: formatAssignmentTypeLabel(node.nodeKind),
    meta: [
      node.authorityRank != null ? `Authority #${node.authorityRank}` : null,
      node.status,
      node.corpusId ?? null,
    ].filter(Boolean),
    span: template.span,
    stamp: formatDateTime(node.updatedAt ?? node.createdAt ?? node.versionCreatedAt ?? ""),
    templateRole: template.role,
    title,
  };
}

function categoryToConceptNewsroomCard(category: CategorySteeringCategory, index: number): NewsroomCardRecord {
  const lineageId = category.lineageId ?? category.id;
  const title = category.displayName;
  const subtitle = distinctNewsroomCardSubtitle(
    title,
    category.subtitle
      ?? category.description
      ?? null,
  );
  const template = resolveNewsroomCardTemplate({
    bodyLength: subtitle?.length ?? 0,
    index,
    isUrgent: category.status === "proposed",
    mode: "desk",
    sectionKey: "concepts",
    title,
    updatedAt: category.updatedAt ?? category.versionCreatedAt ?? null,
  });
  return {
    id: lineageId,
    ariaLabel: `Open concept ${title}`,
    body: subtitle ? newsroomCardExcerpt(subtitle, 220) : null,
    dataAttributes: {
      "data-newsroom-card-node-kind": "category",
      "data-newsroom-card-node-status": category.status ?? "",
    },
    kicker: "Topic",
    meta: [
      category.shortTitle ?? null,
      category.status ?? null,
    ].filter(Boolean),
    span: template.span,
    stamp: formatDateTime(category.updatedAt ?? category.versionCreatedAt ?? ""),
    templateRole: template.role,
    title,
  };
}

function resolveReferenceCardTitle(reference: ReferenceRecord, metadataTitle?: string | null): string {
  return metadataTitle ?? reference.title ?? reference.externalItemId;
}

function referenceToNewsroomCard(
  reference: ReferenceRecord,
  index: number,
  options: {
    title?: string | null;
    subtitle?: string | null;
    qualityRating?: number | null;
  } = {},
): NewsroomCardRecord {
  const lineageId = reference.lineageId ?? reference.id;
  const processingStatus = resolveReferenceProcessingStatus(reference);
  const status = reference.curationStatus ?? "pending";
  const title = resolveReferenceCardTitle(reference, options.title ?? null);
  const subtitle = options.subtitle ?? null;
  const qualityRating = options.qualityRating ?? null;
  const inboundCitationCount = resolveReferenceCitationCount(reference.inboundCitationCount);
  const template = resolveNewsroomCardTemplate({
    bodyLength: subtitle?.length ?? 0,
    index,
    isUrgent: status === "pending",
    mode: "desk",
    qualityRating,
    sectionKey: "references",
    title,
    updatedAt: reference.updatedAt ?? reference.importedAt ?? null,
  });
  return {
    id: lineageId,
    ariaLabel: `Open reference ${title}`,
    body: subtitle ? newsroomCardExcerpt(subtitle, 180) : null,
    kicker: null,
    meta: [processingStatus, `Cited by ${inboundCitationCount}`],
    dataAttributes: {
      "data-newsroom-card-quality": isLowReferenceQualityRating(qualityRating) ? "low" : undefined,
    },
    span: template.span,
    stamp: formatReferenceDate(reference),
    templateRole: template.role,
    title,
  };
}

function resolveReferenceCitationCount(
  value: number | null | undefined,
  fallback = 0,
): number {
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    return Math.trunc(value);
  }
  if (typeof fallback === "number" && Number.isFinite(fallback) && fallback >= 0) {
    return Math.trunc(fallback);
  }
  return 0;
}

function buildCitationReferenceObjects(
  graph: SemanticGraph,
  relations: SemanticRelationRecord[],
  direction: "incoming" | "outgoing",
): SemanticObjectSummary[] {
  const objects = new Map<string, SemanticObjectSummary>();
  for (const relation of relations) {
    const relationSummary = direction === "outgoing"
      ? (
        graph.resolve("reference", relation.objectLineageId)
        ?? graph.resolve("reference", relation.objectId)
        ?? fallbackReferenceSummary(relation.objectId, relation.objectLineageId)
      )
      : (
        graph.resolve("reference", relation.subjectLineageId)
        ?? graph.resolve("reference", relation.subjectId)
        ?? fallbackReferenceSummary(relation.subjectId, relation.subjectLineageId)
      );
    const key = `${relationSummary.kind}#${relationSummary.lineageId}`;
    if (!objects.has(key)) objects.set(key, relationSummary);
  }
  return Array.from(objects.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function fallbackReferenceSummary(id: string, lineageId: string): SemanticObjectSummary {
  const resolvedLineage = lineageId || id;
  return {
    kind: "reference",
    href: newsDeskHrefForSemanticObject("reference", resolvedLineage),
    id: id || resolvedLineage,
    label: resolvedLineage,
    lineageId: resolvedLineage,
  };
}

function resolveReferenceCurationDisplayState(reference: ReferenceRecord, graph: SemanticGraph): ReferenceCurationDisplayState {
  const effectiveStatus = normalizeReferenceStatus(reference.curationStatus);
  const persistedQualityRating = graph.currentReferenceQualityRating(reference.lineageId ?? reference.id);
  return {
    effectiveDisplayedStars: effectiveStatus === "rejected" ? 0 : persistedQualityRating ?? 0,
    effectiveStatus,
    persistedQualityRating,
  };
}

function referenceQualityForList(reference: ReferenceRecord, graph: SemanticGraph): number | null {
  if (normalizeReferenceStatus(reference.curationStatus) === "rejected") return null;
  return graph.currentReferenceQualityRating(reference.lineageId ?? reference.id);
}

function qualityRatingFromRelation(relation: SemanticRelationRecord): number | null {
  const score = typeof relation.score === "number" ? relation.score : Number(relation.score);
  if (Number.isFinite(score) && Number.isInteger(score) && score >= 1 && score <= 5) return score;
  return qualityRatingFromNodeKey(relation.objectLineageId) ?? qualityRatingFromNodeKey(relation.objectId);
}

function qualityRatingFromNodeKey(value: string | null | undefined): number | null {
  const match = /(?:quality[-_.]?rating[-_.]?)?([1-5])[-_.]?star/i.exec(value ?? "");
  return match ? Number(match[1]) : null;
}

function isLowReferenceQualityRating(value: number | null | undefined): boolean {
  return typeof value === "number" && Number.isFinite(value) && value < 3;
}

function upsertReferenceQualityRelations(
  current: SemanticRelationRecord[],
  reference: ReferenceRecord,
  rating: number | null,
  actorLabel: string,
  now: string,
  relationId?: string | null,
): SemanticRelationRecord[] {
  const referenceLineageId = reference.lineageId ?? reference.id;
  const nextRelations = current.map((relation) => (
    relation.relationState === "current"
      && relation.subjectKind === "reference"
      && relation.subjectLineageId === referenceLineageId
      && semanticRelationKind(relation) === "quality_rating_is"
      ? {
          ...relation,
          relationState: "superseded",
          updatedAt: now,
          metadata: JSON.stringify({
            ...metadataRecord(relation.metadata),
            supersededAt: now,
            supersededBy: actorLabel,
          }),
        }
      : relation
  ));
  if (rating === null) return nextRelations;
  const relation = buildUiReferenceQualityRelation(reference, rating, actorLabel, now, relationId ?? undefined);
  return [relation, ...nextRelations.filter((entry) => entry.id !== relation.id)];
}

function buildUiReferenceQualityRelation(
  reference: ReferenceRecord,
  rating: number,
  actorLabel: string,
  now: string,
  relationId?: string,
): SemanticRelationRecord {
  const referenceLineageId = reference.lineageId ?? reference.id;
  const nodeLineageId = qualityNodeLineageId(rating);
  const nodeId = qualityNodeId(rating);
  return {
    id: relationId ?? `semantic-relation-quality-${safeUiId(referenceLineageId)}-${rating}-${now.replace(/[^0-9TZ]/g, "")}`,
    relationState: "current",
    predicate: "quality_rating_is",
    relationTypeId: "semantic-relation-type-quality-rating-is",
    relationTypeKey: "quality_rating_is",
    relationDomain: "curation",
    subjectKind: "reference",
    subjectId: reference.id,
    subjectLineageId: referenceLineageId,
    subjectVersionNumber: reference.versionNumber ?? null,
    objectKind: "semanticNode",
    objectId: nodeId,
    objectLineageId: nodeLineageId,
    objectVersionNumber: 1,
    subjectStateKey: `reference#${referenceLineageId}#current`,
    objectStateKey: `semanticNode#${nodeLineageId}#current`,
    objectSubjectStateKey: `semanticNode#${nodeLineageId}#current#reference`,
    predicateObjectStateKey: `quality_rating_is#semanticNode#${nodeLineageId}#current`,
    subjectVersionKey: `reference#${reference.id}`,
    objectVersionKey: `semanticNode#${nodeId}`,
    score: rating,
    confidence: null,
    rank: 1,
    reviewRecommended: false,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: JSON.stringify({
      actorLabel,
      kind: "reference.quality-rating.manual",
      qualityRating: rating,
      ratedAt: now,
    }),
  };
}

function qualityNodeLineageId(rating: number): string {
  return `semantic-node-quality-rating-${rating}-star`;
}

function qualityNodeId(rating: number): string {
  return `${qualityNodeLineageId(rating)}-v1`;
}

function messageToNewsroomCard(message: MessageRecord, index: number): NewsroomCardRecord {
  const subtitle = messageCardSubtitle(message);
  const template = resolveNewsroomCardTemplate({
    bodyLength: subtitle?.length ?? 0,
    index,
    isUrgent: message.status !== "archived",
    mode: "desk",
    sectionKey: "messages",
    title: message.summary ?? message.id,
    updatedAt: message.updatedAt ?? message.createdAt ?? null,
  });
  return {
    id: message.id,
    ariaLabel: `Open message ${message.summary ?? message.id}`,
    body: subtitle ? newsroomCardExcerpt(subtitle, 180) : null,
    kicker: message.messageKind,
    meta: [
      message.messageDomain,
      message.authorLabel ?? message.authorSub ?? "unknown author",
      message.source ?? message.status,
    ],
    span: template.span,
    stamp: formatDateTime(message.createdAt),
    templateRole: template.role,
    title: message.summary ?? "Stored message payload",
  };
}

function consoleThreadToMessageRecord(thread: ConsoleThreadSummary): MessageRecord {
  const updatedAt = thread.updatedAt ?? thread.lastMessageAt ?? thread.createdAt;
  return {
    id: thread.id,
    messageKind: "console_thread",
    messageDomain: "conversation",
    status: thread.status,
    summary: thread.summary ?? thread.title,
    source: "papyrus-console",
    authorLabel: thread.createdByLabel ?? null,
    createdAt: thread.createdAt,
    updatedAt,
    newsroomFeedKey: thread.newsroomFeedKey ?? "consoleChat",
    metadata: {
      threadId: thread.id,
      threadKind: thread.threadKind,
      messageCount: thread.messageCount ?? 0,
      lastMessageAt: thread.lastMessageAt ?? null,
      primaryAnchorKey: thread.primaryAnchorKey ?? null,
    },
  };
}

function assignmentToNewsroomCard(assignment: AssignmentRecord, index: number, reportingDecision: ReportingPacketDecisionSummary | null = null): NewsroomCardRecord {
  const analysisPlan = assignmentAnalysisReindexMetadata(assignment);
  const subtitle = assignmentCardSubtitle(assignment);
  const priority = typeof assignment.priority === "number" ? assignment.priority : null;
  const template = resolveNewsroomCardTemplate({
    bodyLength: subtitle?.length ?? 0,
    index,
    isUrgent: assignment.status === "open" || assignment.status === "claimed" || (priority !== null && priority <= 1),
    mode: "desk",
    sectionKey: "assignments",
    title: assignment.title,
    updatedAt: assignment.updatedAt ?? assignment.createdAt ?? null,
  });
  return {
    id: assignment.id,
    ariaLabel: `Open assignment ${assignment.title}`,
    body: subtitle ? newsroomCardExcerpt(subtitle, 180) : null,
    dataAttributes: {
      "data-assignment-candidate": assignment.id,
      "data-assignment-status": assignment.status,
    },
    kicker: formatAssignmentTypeLabel(assignment.assignmentTypeKey),
    meta: [
      reportingDecision ? `reporting ${reportingDecision.decision}` : null,
      analysisPlan ? analysisPlan.profileTitle : assignment.queueKey,
      assignment.assigneeKey ?? assignment.assigneeType ?? "unassigned",
      formatDateTime(assignment.updatedAt ?? assignment.createdAt),
    ].filter(Boolean),
    span: template.span,
    stamp: <StatusPill status={assignment.status} />,
    templateRole: template.role,
    title: assignment.title,
  };
}

function messageCardSubtitle(message: MessageRecord): string | null {
  return distinctNewsroomCardSubtitle(
    message.summary ?? null,
    deriveDelimitedSubtitle(message.summary)
      ?? null,
  );
}

type ReferenceMetadataFields = {
  title: string | null;
  subtitle: string | null;
};

const referenceMetadataFieldsCache = new Map<string, { fields: ReferenceMetadataFields; revision: string }>();

function mapsEqualReferenceMetadataFields(a: Map<string, ReferenceMetadataFields>, b: Map<string, ReferenceMetadataFields>): boolean {
  if (a.size !== b.size) return false;
  for (const [key, value] of a) {
    const other = b.get(key);
    if (!other) return false;
    if ((other.title ?? null) !== (value.title ?? null)) return false;
    if ((other.subtitle ?? null) !== (value.subtitle ?? null)) return false;
  }
  return true;
}

function useReferenceMetadataFields(references: ReferenceRecord[]): Map<string, ReferenceMetadataFields> {
  const [fieldsByReferenceId, setFieldsByReferenceId] = useState<Map<string, ReferenceMetadataFields>>(() => new Map());
  const subscriptionClient = useMemo(
    () => generateClient<Schema>({ authMode: USER_POOL_AUTH_MODE }),
    [],
  );
  const referenceMeta = useMemo(
    () => references.map((reference) => ({
      id: reference.id,
      revision: `${reference.id}:${reference.updatedAt ?? reference.importedAt ?? ""}`,
    })).filter((entry) => Boolean(entry.id)),
    [references],
  );
  const referenceKey = useMemo(
    () => referenceMeta.map((entry) => entry.revision).join("|"),
    [referenceMeta],
  );
  const visibleReferenceIds = useMemo(
    () => new Set(referenceMeta.map((entry) => entry.id)),
    [referenceMeta],
  );

  useEffect(() => {
    if (!referenceMeta.length) {
      setFieldsByReferenceId((current) => (current.size ? new Map() : current));
      return;
    }

    const cached = new Map<string, ReferenceMetadataFields>();
    const missing: Array<{ id: string; revision: string }> = [];
    for (const entry of referenceMeta) {
      const referenceId = entry.id;
      const cachedEntry = referenceMetadataFieldsCache.get(referenceId);
      if (
        cachedEntry
        && cachedEntry.revision === entry.revision
      ) {
        cached.set(referenceId, cachedEntry.fields);
      } else {
        if (cachedEntry) referenceMetadataFieldsCache.delete(referenceId);
        missing.push(entry);
      }
    }
    setFieldsByReferenceId((current) => (mapsEqualReferenceMetadataFields(current, cached) ? current : cached));
    if (!missing.length) return;

    let active = true;
    Promise.all(missing.map(async ({ id: referenceId, revision }) => {
      try {
        const payloads = await loadModelPayloadsForOwner("reference", referenceId, ["metadata"]);
        const metadataPayload = modelPayloadByRole(payloads, "metadata");
        const fields = {
          title: referenceMetadataTitle(metadataPayload),
          subtitle: referenceMetadataSubtitle(metadataPayload),
        };
        referenceMetadataFieldsCache.set(referenceId, { fields, revision });
        return [referenceId, fields] as const;
      } catch {
        const fields = { title: null, subtitle: null };
        referenceMetadataFieldsCache.set(referenceId, { fields, revision });
        return [referenceId, fields] as const;
      }
    })).then((entries) => {
      if (!active) return;
      setFieldsByReferenceId((current) => {
        const next = new Map(current);
        for (const [referenceId, fields] of entries) next.set(referenceId, fields);
        return next;
      });
    });

    return () => {
      active = false;
    };
  }, [referenceKey, referenceMeta]);

  useEffect(() => {
    const attachmentModel = subscriptionClient.models.ModelAttachment as unknown as ModelAttachmentSubscriptionModel | undefined;
    if (!attachmentModel || typeof attachmentModel.onCreate !== "function" || typeof attachmentModel.onUpdate !== "function") return;
    if (!visibleReferenceIds.size) return;

    let active = true;
    const refreshReference = async (referenceId: string) => {
      const nextRevision = `${referenceId}:attachment`;
      try {
        const payloads = await loadModelPayloadsForOwner("reference", referenceId, ["metadata"]);
        if (!active) return;
        const metadataPayload = modelPayloadByRole(payloads, "metadata");
        const fields = {
          title: referenceMetadataTitle(metadataPayload),
          subtitle: referenceMetadataSubtitle(metadataPayload),
        };
        referenceMetadataFieldsCache.set(referenceId, { fields, revision: nextRevision });
        setFieldsByReferenceId((current) => {
          const existing = current.get(referenceId);
          if (existing && existing.title === fields.title && existing.subtitle === fields.subtitle) return current;
          const next = new Map(current);
          next.set(referenceId, fields);
          return next;
        });
      } catch {
        if (!active) return;
      }
    };

    const handleAttachmentEvent = (value: unknown) => {
      const attachment = normalizeModelAttachmentSubscriptionPayload(value);
      if (!attachment) return;
      if (attachment.ownerKind !== "reference") return;
      if (attachment.role !== "metadata") return;
      if (!visibleReferenceIds.has(attachment.ownerId)) return;
      void refreshReference(attachment.ownerId);
    };

    const subscriptions: ReferenceSubscription[] = [
      attachmentModel.onCreate().subscribe({ next: handleAttachmentEvent }),
      attachmentModel.onUpdate().subscribe({ next: handleAttachmentEvent }),
    ];
    if (typeof attachmentModel.onDelete === "function") {
      subscriptions.push(attachmentModel.onDelete().subscribe({ next: handleAttachmentEvent }));
    }

    return () => {
      active = false;
      for (const subscription of subscriptions) subscription.unsubscribe();
    };
  }, [subscriptionClient, visibleReferenceIds]);

  return fieldsByReferenceId;
}

function referenceMetadataSubtitle(payload: HydratedModelPayload | null, fallback?: unknown): string | null {
  return referenceMetadataField(payload, fallback, "subtitle");
}

function referenceMetadataTitle(payload: HydratedModelPayload | null, fallback?: unknown): string | null {
  return referenceMetadataField(payload, fallback, "title");
}

function normalizeReferenceDetailSummaryForDisplay(summary: string | null, sourceUri?: string | null): string | null {
  const trimmed = summary?.trim();
  if (!trimmed) return null;

  const normalizedSourceUri = normalizeReferenceDetailSourceUri(sourceUri);
  if (!normalizedSourceUri) return trimmed;

  const lines = trimmed.split(/\r?\n/);
  const firstNonEmptyLineIndex = lines.findIndex((line) => line.trim().length > 0);
  if (firstNonEmptyLineIndex < 0) return null;
  const firstLine = lines[firstNonEmptyLineIndex];
  const normalizedFirstLineUri = normalizeReferenceDetailSourceUri(firstLine)
    ?? normalizeReferenceDetailSourceUri(extractReferenceDetailFirstUri(firstLine));
  if (!normalizedFirstLineUri || normalizedFirstLineUri !== normalizedSourceUri) return trimmed;

  let startIndex = firstNonEmptyLineIndex + 1;
  if (startIndex < lines.length && lines[startIndex].trim().length === 0) startIndex += 1;
  const nextSummary = lines.slice(startIndex).join("\n").trim();
  return nextSummary || null;
}

function normalizeReferenceDetailSubtitleForDisplay(subtitle: string | null, sourceUri?: string | null): string | null {
  const trimmed = subtitle?.trim();
  if (!trimmed) return null;
  const normalizedSubtitleUri = normalizeReferenceDetailSourceUri(trimmed)
    ?? normalizeReferenceDetailSourceUri(extractReferenceDetailFirstUri(trimmed));
  if (!normalizedSubtitleUri) return trimmed;
  const normalizedSourceUri = normalizeReferenceDetailSourceUri(sourceUri);
  if (!normalizedSourceUri) return trimmed;
  return normalizedSubtitleUri === normalizedSourceUri ? null : trimmed;
}

function normalizeReferenceDetailSourceUri(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;

  const markdownLinkMatch = trimmed.match(/^\[[^\]]+\]\(([^)]+)\)$/);
  const unwrapped = markdownLinkMatch ? markdownLinkMatch[1].trim() : trimmed.replace(/^<|>$/g, "").trim();
  if (!unwrapped) return null;

  const urlCandidateMatch = unwrapped.match(/^(https?:\/\/\S+|s3:\/\/\S+)$/i);
  if (!urlCandidateMatch) return null;

  try {
    const parsed = new URL(urlCandidateMatch[1]);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      const normalizedPath = parsed.pathname !== "/" ? parsed.pathname.replace(/\/+$/, "") : "/";
      return `${parsed.protocol}//${parsed.host}${normalizedPath}${parsed.search}${parsed.hash}`;
    }
    return parsed.toString();
  } catch {
    return urlCandidateMatch[1];
  }
}

function normalizeReferenceDetailHttpUri(value: string | null | undefined): string | null {
  const normalized = normalizeReferenceDetailSourceUri(value);
  if (!normalized) return null;
  if (normalized.startsWith("http://") || normalized.startsWith("https://")) return normalized;
  return null;
}

function extractReferenceDetailFirstUri(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = value.match(/(https?:\/\/[^\s)\]>]+|s3:\/\/[^\s)\]>]+)/i);
  if (!match?.[1]) return null;
  return match[1].replace(/[.,;:!?]+$/, "");
}

function metadataRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "string") {
    try {
      return metadataRecord(JSON.parse(value));
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function humanizeNewsroomLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function assignmentCardSubtitle(assignment: AssignmentRecord): string | null {
  return distinctNewsroomCardSubtitle(
    assignment.title,
    normalizeMetadataString(assignment.summary)
      ?? deriveDelimitedSubtitle(assignment.title)
      ?? assignmentBriefSubtitle(assignment)
      ?? assignmentFocusSubtitle(assignment)
      ?? null,
  );
}

function assignmentBriefSubtitle(assignment: AssignmentRecord): string | null {
  const brief = normalizeMetadataString(assignment.brief);
  if (!brief) return null;
  return brief.length > 180 ? `${brief.slice(0, 177).trimEnd()}...` : brief;
}

function assignmentFocusSubtitle(assignment: AssignmentRecord): string | null {
  const parts = [
    normalizeMetadataString(assignment.primaryFocusCategoryKey),
    normalizeMetadataStringList(assignment.topicScopeCategoryKeys)[0] ?? null,
    normalizeMetadataString(assignment.sectionKey),
  ].filter((value): value is string => Boolean(value));
  return distinctNewsroomCardSubtitle(
    assignment.title,
    parts.length ? parts.join(" / ") : null,
  );
}

function distinctNewsroomCardSubtitle(title: string | null | undefined, subtitle: string | null | undefined): string | null {
  const normalizedTitle = normalizeMetadataString(title);
  const normalizedSubtitle = normalizeMetadataString(subtitle);
  if (!normalizedSubtitle) return null;
  if (!normalizedTitle) return normalizedSubtitle;
  return normalizedSubtitle === normalizedTitle ? null : normalizedSubtitle;
}

function deriveDelimitedSubtitle(value: string | null | undefined): string | null {
  const text = normalizeMetadataString(value);
  if (!text) return null;
  for (const delimiter of [": ", " - ", " | "]) {
    const index = text.indexOf(delimiter);
    if (index <= 0) continue;
    const subtitle = text.slice(index + delimiter.length).trim();
    if (subtitle) return subtitle;
  }
  return null;
}

function newsroomCardExcerpt(value: string | null | undefined, maxLength: number): string | null {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return null;
  if (text.length <= maxLength) return text;
  const clipped = text.slice(0, maxLength - 3).replace(/\s+\S*$/, "").trim();
  return `${clipped || text.slice(0, maxLength - 3)}...`;
}

function formatCompactCount(value: number): string {
  const parts = formatCompactCountParts(value);
  return `${parts.value}${parts.suffix}`;
}

function newsroomSummaryStatus(dashboard: Pick<CategorySteeringDashboard, "summary" | "summaryStatus">): "loading" | "missing" | "ready" {
  if (dashboard.summary) return "ready";
  return dashboard.summaryStatus ?? "loading";
}

function formatOverviewCountDetail(
  status: "loading" | "missing" | "ready",
  count: number | null,
  label: string,
): string {
  if (status === "missing") return `? ${label}`;
  if (typeof count === "number") return `${count} ${label}`;
  return label;
}

function formatOverviewDualCountDetail(
  status: "loading" | "missing" | "ready",
  primaryCount: number | null,
  primaryLabel: string,
  secondaryCount: number | null,
  secondaryLabel: string,
): string {
  if (status === "missing") return `? ${primaryLabel} / ? ${secondaryLabel}`;
  if (typeof primaryCount === "number" && typeof secondaryCount === "number") {
    return `${primaryCount} ${primaryLabel} / ${secondaryCount} ${secondaryLabel}`;
  }
  return `${primaryLabel} / ${secondaryLabel}`;
}

function summaryCount(dashboard: Pick<CategorySteeringDashboard, "summary">, key: string): number | null {
  return dashboard.summary ? (dashboard.summary.counts?.[key] ?? 0) : null;
}

function summaryCountFromRecord(summary: NewsroomSummaryRecord | null | undefined, key: string): number | null {
  return summary ? (summary.counts?.[key] ?? 0) : null;
}

function isCurrentCategorySet(categorySet: CategorySteeringCategorySet): boolean {
  return categorySet.versionState === "current" && categorySet.status === "accepted";
}

function isDraftCategorySet(categorySet: CategorySteeringCategorySet): boolean {
  return categorySet.versionState === "draft" && categorySet.status === "draft";
}

function isSelectableTopicCategorySet(categorySet: CategorySteeringCategorySet): boolean {
  return isCurrentCategorySet(categorySet) || isDraftCategorySet(categorySet);
}

function topicCategorySetTimestamp(categorySet: CategorySteeringCategorySet): number {
  const value = categorySet.generatedAt ?? categorySet.updatedAt ?? categorySet.createdAt ?? "";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function activeDraftForCurrentCategorySet(
  categorySets: CategorySteeringCategorySet[],
  categorys: CategorySteeringCategory[],
  currentCategorySet: CategorySteeringCategorySet | null,
): CategorySteeringCategorySet | null {
  if (!currentCategorySet) return null;
  const currentLineageId = currentCategorySet.lineageId ?? currentCategorySet.id;
  const activeCategoryCounts = new Map<string, number>();
  for (const category of categorys) {
    if (category.status === "deprecated" || category.status === "archived" || category.versionState === "superseded") continue;
    activeCategoryCounts.set(category.categorySetId, (activeCategoryCounts.get(category.categorySetId) ?? 0) + 1);
  }
  return categorySets
    .filter(isDraftCategorySet)
    .filter((categorySet) => (categorySet.lineageId ?? categorySet.id) === currentLineageId)
    .filter((categorySet) => (activeCategoryCounts.get(categorySet.id) ?? 0) > 0)
    .sort((left, right) => topicCategorySetTimestamp(right) - topicCategorySetTimestamp(left) || left.id.localeCompare(right.id))[0] ?? null;
}

function resolveTopicWorkspace(
  categorySets: CategorySteeringCategorySet[],
  selectedCategorySetId: string | null,
  currentCategorySetId: string | null,
): CategorySteeringCategorySet | null {
  if (selectedCategorySetId) {
    const selected = categorySets.find((categorySet) => categorySet.id === selectedCategorySetId) ?? null;
    if (selected && isDraftCategorySet(selected)) return selected;
    if (selected && isCurrentCategorySet(selected)) return selected;
  }
  if (!currentCategorySetId) return null;
  return categorySets.find((categorySet) => categorySet.id === currentCategorySetId && isCurrentCategorySet(categorySet)) ?? null;
}

function formatCompactCountParts(value: number): { value: string; suffix: string } {
  const count = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  if (count < 1000) return { value: String(count), suffix: "" };
  if (count < 10_000) return { value: formatScaledCount(count / 1000), suffix: "K" };
  if (count < 1_000_000) return { value: String(Math.round(count / 1000)), suffix: "K" };
  if (count < 10_000_000) return { value: formatScaledCount(count / 1_000_000), suffix: "M" };
  if (count < 1_000_000_000) return { value: String(Math.round(count / 1_000_000)), suffix: "M" };
  return { value: String(Math.round(count / 1_000_000_000)), suffix: "B" };
}

function formatScaledCount(value: number): string {
  return value.toFixed(1).replace(/\.0$/, "");
}

function selectReferenceSummary(graph: SemanticGraph, references: ReferenceRecord[], lineageId?: string | null): SemanticObjectSummary | null {
  const selected = lineageId ? graph.resolve("reference", lineageId) : null;
  if (selected) return selected;
  const first = references[0];
  return first ? graph.resolve("reference", first.lineageId ?? first.id) : null;
}

function selectSemanticNodeSummary(graph: SemanticGraph, nodes: SemanticNodeRecord[], lineageId?: string | null): SemanticObjectSummary | null {
  const selected = lineageId ? graph.resolve("semanticNode", lineageId) : null;
  if (selected) return selected;
  if (lineageId) {
    const matched = nodes.find((node) => (
      (node.lineageId ?? node.id) === lineageId
      || node.id === lineageId
      || node.nodeKey === lineageId
    ));
    if (matched) return summarizeSemanticNodeSummary(matched);
    return null;
  }
  const first = nodes[0];
  if (!first) return null;
  return graph.resolve("semanticNode", first.lineageId ?? first.id) ?? summarizeSemanticNodeSummary(first);
}

function selectCategorySummary(graph: SemanticGraph, categories: CategorySteeringCategory[], lineageId?: string | null): SemanticObjectSummary | null {
  const selected = lineageId ? graph.resolve("category", lineageId) : null;
  if (selected) return selected;
  if (lineageId) {
    const matched = categories.find((category) => (
      categoryLineageId(category) === lineageId
      || category.id === lineageId
      || category.categoryKey === lineageId
    ));
    if (matched) return summarizeCategorySummary(matched);
    return null;
  }
  const first = categories[0];
  if (!first) return null;
  return graph.resolve("category", categoryLineageId(first)) ?? summarizeCategorySummary(first);
}

function summarizeSemanticNodeSummary(node: SemanticNodeRecord): SemanticObjectSummary {
  const lineageId = node.lineageId ?? node.id;
  return {
    kind: "semanticNode",
    id: node.id,
    lineageId,
    versionNumber: node.versionNumber,
    label: node.displayName ?? node.nodeKey,
    subtitle: node.nodeKind,
    href: newsDeskHrefForSemanticObject("semanticNode", lineageId),
    record: node,
  };
}

function summarizeCategorySummary(category: CategorySteeringCategory): SemanticObjectSummary {
  const lineageId = categoryLineageId(category);
  return {
    kind: "category",
    id: category.id,
    lineageId,
    versionNumber: category.versionNumber,
    label: category.displayName,
    subtitle: category.subtitle ?? category.categoryKey,
    href: newsDeskHrefForSemanticObject("category", lineageId),
    record: category,
  };
}

type AssignmentMetrics = {
  total: number;
  open: number;
  claimed: number;
  completed: number;
  canceled: number;
};

type AssignmentTypeOption = {
  key: string;
  label: string;
  count: number;
};

function getAssignmentTypeOptions(assignments: AssignmentRecord[], summary?: NewsroomSummaryRecord | null): AssignmentTypeOption[] {
  const summaryCounts = summary?.facets?.assignments?.byType ?? summary?.assignmentTypeCounts;
  const countByType = summaryCounts && Object.keys(summaryCounts).length
    ? new Map(Object.entries(summaryCounts))
    : new Map<string, number>();
  if (!countByType.size) {
    for (const assignment of assignments) {
      const typeKey = assignmentTypeKeyForFilter(assignment);
      countByType.set(typeKey, (countByType.get(typeKey) ?? 0) + 1);
    }
  }
  return Array.from(countByType.entries())
    .map(([key, count]) => ({
      key,
      label: formatAssignmentTypeLabel(key),
      count,
    }))
    .sort((left, right) => {
      const countDiff = right.count - left.count;
      if (countDiff !== 0) return countDiff;
      return left.label.localeCompare(right.label);
    });
}

function assignmentTypeKeyForFilter(assignment: AssignmentRecord): string {
  return assignment.assignmentTypeKey?.trim() || "unknown";
}

function formatAssignmentTypeLabel(typeKey: string | null | undefined): string {
  const key = typeKey?.trim();
  if (!key) return "Uncategorized";
  if (key === "analysis.reindex") return "Analysis re-index";
  if (key === "newsroom.research" || key === "research") return "Research";
  if (key === "curation.reference-intake") return "Reference intake";
  return key
    .split(/[.:_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function getAssignmentMetrics(assignments: AssignmentRecord[], summary?: NewsroomSummaryRecord | null, typeFilter?: string): AssignmentMetrics {
  const statusCounts = typeFilter
    ? summary?.facets?.assignments?.statusByType?.[typeFilter]
    : summary?.facets?.assignments?.byStatus ?? summary?.assignmentStatusCounts;
  if (statusCounts && Object.keys(statusCounts).length) {
    return {
      total: Object.values(statusCounts).reduce((sum, count) => sum + count, 0),
      open: statusCounts.open ?? 0,
      claimed: statusCounts.claimed ?? 0,
      completed: statusCounts.completed ?? 0,
      canceled: statusCounts.canceled ?? 0,
    };
  }
  return {
    total: assignments.length,
    open: assignments.filter((assignment) => assignment.status === "open").length,
    claimed: assignments.filter((assignment) => assignment.status === "claimed").length,
    completed: assignments.filter((assignment) => assignment.status === "completed").length,
    canceled: assignments.filter((assignment) => assignment.status === "canceled").length,
  };
}

function compareAssignments(left: AssignmentRecord, right: AssignmentRecord): number {
  const leftStatus = assignmentStatusRank(left.status);
  const rightStatus = assignmentStatusRank(right.status);
  if (leftStatus !== rightStatus) return leftStatus - rightStatus;
  const priorityDiff = (left.priority ?? 999999) - (right.priority ?? 999999);
  if (priorityDiff !== 0) return priorityDiff;
  return left.createdAt.localeCompare(right.createdAt);
}

function assignmentStatusRank(status: string): number {
  if (status === "open") return 0;
  if (status === "claimed") return 1;
  if (status === "completed") return 6;
  if (status === "canceled") return 8;
  return 5;
}

function applyAssignmentActionLocally(assignment: AssignmentRecord, action: AssignmentAction, now: string): AssignmentRecord {
  const status = action === "claim"
    ? "claimed"
    : action === "retry"
    ? "claimed"
    : action === "release" || action === "reopen"
      ? "open"
      : action === "complete"
        ? "completed"
        : action === "cancel"
          ? "canceled"
          : assignment.status;
  return {
    ...assignment,
    status,
    queueStatusKey: `${assignment.queueKey}#${status}`,
    claimedAt: action === "claim" || action === "retry" ? now : action === "release" ? null : assignment.claimedAt,
    completedAt: action === "complete" ? now : action === "reopen" ? null : assignment.completedAt,
    canceledAt: action === "cancel" ? now : action === "reopen" ? null : assignment.canceledAt,
    updatedAt: now,
  };
}

function assignmentExecutionModeForUi(assignmentTypeKey: string | null | undefined): "immediate" | "queued" {
  return assignmentTypeKey === "procedure.run" ? "immediate" : "queued";
}

function demoAssignmentEvent(assignment: AssignmentRecord, action: AssignmentAction, now: string, note: string): AssignmentEventRecord {
  const next = applyAssignmentActionLocally(assignment, action, now);
  return {
    id: `assignment-event-demo-${assignment.id}-${now}`,
    assignmentId: assignment.id,
    assignmentTypeKey: assignment.assignmentTypeKey,
    queueKey: assignment.queueKey,
    eventType: action,
    fromStatus: assignment.status,
    toStatus: next.status,
    actorLabel: "Papyrus newsroom",
    note: note.trim() || null,
    createdAt: now,
  };
}

function latestReportingPacketDecisionForAssignment(events: AssignmentEventRecord[], assignmentId: string): ReportingPacketDecisionSummary | null {
  const event = events
    .filter((entry) => entry.assignmentId === assignmentId && entry.eventType.startsWith("reporting_"))
    .sort((left, right) => String(right.createdAt).localeCompare(String(left.createdAt)))[0];
  if (!event) return null;
  const metadata = parseMetadataObject(event.metadata) ?? {};
  const decision = normalizeReportingPacketDecision(metadata.decision ?? event.eventType.replace(/^reporting_/, ""));
  if (!decision) return null;
  return {
    decision,
    copywritingAssignmentId: normalizeMetadataString(metadata.copywritingAssignmentId),
    copywritingStatus: normalizeMetadataString(metadata.copywritingStatus),
    draftItemId: normalizeMetadataString(metadata.draftItemId),
    eventId: event.id,
    note: event.note ?? null,
    targetItemId: normalizeMetadataString(metadata.targetItemId),
  };
}

function buildUiReportingPacketReviewPlan({
  actorLabel,
  assignment,
  decision,
  message,
  note,
  now,
  targetItem = null,
  targetItemId = "",
}: {
  actorLabel: string;
  assignment: AssignmentRecord;
  decision: ReportingPacketReviewDecision;
  message: MessageRecord;
  note: string;
  now: string;
  targetItem?: UiReportingReviewItemTarget | null;
  targetItemId?: string;
}): {
  copywritingAssignment: AssignmentRecord | null;
  event: AssignmentEventRecord;
  relations: SemanticRelationRecord[];
} {
  if (assignment.assignmentTypeKey !== "reporting.edition-candidate") throw new Error("Only reporting edition-candidate assignments can review reporting packets.");
  if (message.messageKind !== "reporting_context_packet") throw new Error("Only reporting context packets can be reviewed.");
  if (decision === "merge" && !targetItem?.id && !targetItemId.trim()) throw new Error("Merge Packet requires a target Item ID.");
  const resolvedTargetItem = targetItem ?? (targetItemId.trim() ? { id: targetItemId.trim(), lineageId: targetItemId.trim(), versionNumber: null } : null);
  const copywritingAssignment = decision === "select" || decision === "brief"
    ? buildUiCopywritingAssignment({ actorLabel, assignment, decision, message, now })
    : null;
  const eventType = `reporting_${decision}`;
  const metadata = {
    kind: "reporting.packet_review",
    source: "newsroom",
    assignmentId: assignment.id,
    messageId: message.id,
    decision,
    targetItemId: resolvedTargetItem?.id ?? null,
    copywritingAssignmentId: copywritingAssignment?.id ?? null,
    copywritingStatus: copywritingAssignment?.status ?? null,
    targetItemType: copywritingAssignment?.assignmentTypeKey === "copywriting.brief-draft" ? "brief" : copywritingAssignment ? "article" : null,
    draftItemId: null,
    createsCopywritingAssignment: Boolean(copywritingAssignment),
    createsDraftItem: false,
    privatePacketMessageKind: "reporting_context_packet",
    createsEditionItem: false,
  };
  const event: AssignmentEventRecord = {
    id: `assignment-event-${safeUiId(assignment.id)}-${safeUiId(eventType)}-${timestampUiId(now)}`,
    assignmentId: assignment.id,
    assignmentTypeKey: assignment.assignmentTypeKey,
    queueKey: assignment.queueKey,
    eventType,
    fromStatus: assignment.status,
    toStatus: assignment.status,
    actorLabel,
    note: note.trim() || null,
    createdAt: now,
    metadata,
  };
  const relations: SemanticRelationRecord[] = [];
  if (copywritingAssignment) {
    relations.push(buildUiDerivedFromRelation({
      subjectAssignment: copywritingAssignment,
      objectKind: "assignment",
      objectId: assignment.id,
      objectLineageId: assignment.id,
      decision,
      messageId: message.id,
      now,
      rank: 1,
    }));
    relations.push(buildUiDerivedFromRelation({
      subjectAssignment: copywritingAssignment,
      objectKind: "message",
      objectId: message.id,
      objectLineageId: message.id,
      decision,
      messageId: message.id,
      now,
      rank: 2,
    }));
  }
  if (resolvedTargetItem && decision === "merge") {
    relations.push(buildUiProducesRelation({ assignment, item: resolvedTargetItem, decision, messageId: message.id, now }));
  }
  return { copywritingAssignment, event, relations };
}

function buildUiCopywritingAssignment({ actorLabel, assignment, decision, message, now }: {
  actorLabel: string;
  assignment: AssignmentRecord;
  decision: ReportingPacketReviewDecision;
  message: MessageRecord;
  now: string;
}): AssignmentRecord {
  const type = decision === "brief" ? "brief" : "article";
  const assignmentTypeKey = type === "brief" ? "copywriting.brief-draft" : "copywriting.article-draft";
  const section = assignment.sectionKey ?? assignment.sectionId ?? "unsectioned";
  const id = `assignment-copywriting-${safeUiId(type)}-${hashUiKey([assignment.id, message.id, decision])}`;
  const queueKey = `copywriting:${section}:type:${type}`;
  const assignmentMetadata = parseMetadataObject(assignment.metadata) ?? {};
  const messageMetadata = parseMetadataObject(message.metadata) ?? {};
  const reporting = parseMetadataObject(messageMetadata.reporting) ?? messageMetadata;
  const copywriterBrief = normalizeMetadataString(reporting.copywriterBrief)
    ?? normalizeMetadataString(reporting.copywriter_brief)
    ?? `Draft a reader-facing ${type} from the selected private reporting packet.`;
  const metadata = {
    kind: "copywriting.assignment",
    createdFrom: "reporting_packet_selection",
    sourceReportingAssignmentId: assignment.id,
    sourceReportingPacketMessageId: message.id,
    decision,
    targetItemType: type,
    sectionKey: section,
    editionId: normalizeMetadataString(reporting.editionId) ?? normalizeMetadataString(reporting.edition_id) ?? normalizeMetadataString(assignmentMetadata.editionId),
    coverageConceptKey: normalizeMetadataString(reporting.coverageConceptKey) ?? normalizeMetadataString(reporting.coverage_concept_key) ?? normalizeMetadataString(assignmentMetadata.coverageConceptKey),
    acceptedReferenceIds: Array.isArray(reporting.acceptedReferenceIds) ? reporting.acceptedReferenceIds : reporting.accepted_reference_ids ?? [],
    proposedReferences: Array.isArray(reporting.proposedReferences) ? reporting.proposedReferences : reporting.proposed_references ?? [],
    storyCycleRunId: normalizeMetadataString(assignmentMetadata.storyCycleRunId),
  };
  return {
    id,
    assignmentTypeKey,
    queueKey,
    queueStatusKey: `${queueKey}#open`,
    status: "open",
    priority: (assignment.priority ?? 100) + 1,
    title: `${type === "brief" ? "Write brief" : "Write article"} from ${assignment.title}`,
    summary: `Copywriting handoff for selected ${type} packet from ${assignment.title}.`,
    brief: copywriterBrief,
    instructions: "Create a reader-facing draft Item from the selected private reporting packet. Do not create EditionItem placement.",
    corpusId: assignment.corpusId ?? null,
    categorySetId: assignment.categorySetId ?? null,
    classifierId: assignment.classifierId ?? null,
    sectionId: assignment.sectionId ?? section,
    sectionKey: section,
    sectionType: assignment.sectionType ?? null,
    sectionStatusKey: `${section}#open`,
    sectionQueueStatusKey: `${section}#${queueKey}#open`,
    primaryFocusCategoryKey: assignment.primaryFocusCategoryKey ?? null,
    topicScopeCategoryKeys: assignment.topicScopeCategoryKeys ?? null,
    sourceSnapshotId: assignment.sourceSnapshotId ?? null,
    importRunId: assignment.importRunId ?? null,
    createdBy: actorLabel,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "assignment#open",
    metadata,
  };
}

function buildUiProducesRelation({ assignment, decision, item, messageId, now }: {
  assignment: AssignmentRecord;
  decision: ReportingPacketReviewDecision;
  item: UiReportingReviewItemTarget;
  messageId: string;
  now: string;
}): SemanticRelationRecord {
  const itemLineageId = item.lineageId ?? item.id;
  const subjectStateKey = semanticStateKey("assignment", assignment.id);
  const objectStateKey = semanticStateKey("item", itemLineageId);
  const subjectVersionKey = semanticVersionKey("assignment", assignment.id);
  const objectVersionKey = semanticVersionKey("item", item.id);
  return {
    id: `semantic-relation-${hashUiKey([subjectVersionKey, "produces", objectVersionKey])}`,
    relationState: "current",
    predicate: "produces",
    relationTypeId: "semantic-relation-type-produces",
    relationTypeKey: "produces",
    relationDomain: "workflow",
    subjectKind: "assignment",
    subjectId: assignment.id,
    subjectLineageId: assignment.id,
    subjectVersionNumber: null,
    objectKind: "item",
    objectId: item.id,
    objectLineageId: itemLineageId,
    objectVersionNumber: item.versionNumber ?? null,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#assignment`,
    predicateObjectStateKey: `produces#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: 1,
    confidence: null,
    rank: 1,
    classifierId: assignment.classifierId ?? null,
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: assignment.sourceSnapshotId ?? null,
    importRunId: assignment.importRunId ?? null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: {
      lifecycle: "reporting-packet-review",
      decision,
      assignmentId: assignment.id,
      messageId,
    },
  };
}

function buildUiDerivedFromRelation({
  subjectAssignment,
  objectKind,
  objectId,
  objectLineageId,
  decision,
  messageId,
  now,
  rank,
}: {
  subjectAssignment: AssignmentRecord;
  objectKind: "assignment" | "message";
  objectId: string;
  objectLineageId: string;
  decision: ReportingPacketReviewDecision;
  messageId: string;
  now: string;
  rank: number;
}): SemanticRelationRecord {
  const subjectStateKey = semanticStateKey("assignment", subjectAssignment.id);
  const objectStateKey = semanticStateKey(objectKind, objectLineageId);
  const subjectVersionKey = semanticVersionKey("assignment", subjectAssignment.id);
  const objectVersionKey = semanticVersionKey(objectKind, objectId);
  return {
    id: `semantic-relation-${hashUiKey([subjectVersionKey, "derived_from", objectVersionKey, rank])}`,
    relationState: "current",
    predicate: "derived_from",
    relationTypeId: "semantic-relation-type-derived-from",
    relationTypeKey: "derived_from",
    relationDomain: "workflow",
    subjectKind: "assignment",
    subjectId: subjectAssignment.id,
    subjectLineageId: subjectAssignment.id,
    subjectVersionNumber: null,
    objectKind,
    objectId,
    objectLineageId,
    objectVersionNumber: null,
    subjectStateKey,
    objectStateKey,
    objectSubjectStateKey: `${objectStateKey}#assignment`,
    predicateObjectStateKey: `derived_from#${objectStateKey}`,
    subjectVersionKey,
    objectVersionKey,
    score: 1,
    confidence: null,
    rank,
    classifierId: subjectAssignment.classifierId ?? null,
    modelVersion: null,
    reviewRecommended: false,
    sourceSnapshotId: subjectAssignment.sourceSnapshotId ?? null,
    importRunId: subjectAssignment.importRunId ?? null,
    importedAt: now,
    createdAt: now,
    updatedAt: now,
    newsroomFeedKey: "semanticRelations",
    metadata: {
      lifecycle: "reporting-packet-review",
      decision,
      copywritingAssignmentId: subjectAssignment.id,
      messageId,
    },
  };
}

function normalizeReportingPacketDecision(value: unknown): ReportingPacketReviewDecision | null {
  const normalized = String(value ?? "").replace(/^reporting_/, "");
  return ["select", "merge", "brief", "hold", "kill"].includes(normalized) ? normalized as ReportingPacketReviewDecision : null;
}

function formatReportingPacketDecision(decision: ReportingPacketReviewDecision): string {
  if (decision === "select") return "Selected";
  if (decision === "merge") return "Merged";
  if (decision === "brief") return "Briefed";
  if (decision === "hold") return "Held";
  return "Killed";
}

function timestampUiId(value: string): string {
  return value.replace(/[^0-9TZ]/g, "");
}

function clampKnowledgeQueryTokenBudget(value: string | number | null | undefined): number {
  if (typeof value === "number") return Math.max(400, Math.min(20_000, Math.trunc(value) || 1600));
  return Math.max(400, Math.min(20_000, Number.parseInt(value ?? "", 10) || 1600));
}

function normalizeKnowledgeQueryAnchorKind(value: string | null | undefined): KnowledgeQueryAnchor["kind"] | null {
  if (
    value === "assignment"
    || value === "category"
    || value === "categorySet"
    || value === "item"
    || value === "message"
    || value === "newsroomSection"
    || value === "reference"
    || value === "semanticNode"
  ) return value;
  return null;
}

function normalizeNewsroomFromHref(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed.startsWith("/newsroom")) return null;
  return trimmed;
}

function currentNewsroomOriginHref(fallback: string | null): string | null {
  if (typeof window === "undefined") return fallback;
  const current = `${window.location.pathname}${window.location.search}`;
  return current.startsWith("/newsroom/search") ? fallback : normalizeNewsroomFromHref(current);
}

function serializeNewsroomSearchRequest(request: NewsroomSearchRequest | null): string {
  if (!request) return "";
  return JSON.stringify({
    anchor: request.anchor ? {
      id: request.anchor.id,
      kind: request.anchor.kind,
      lineageId: request.anchor.lineageId ?? null,
    } : null,
    from: request.from ?? null,
    maxTokens: request.maxTokens,
    semanticQuery: request.semanticQuery,
  });
}

function buildNewsroomSearchHref(request: NewsroomSearchRequest, demo?: boolean): string {
  const params = new URLSearchParams();
  const query = request.semanticQuery.trim();
  const hasPayload = Boolean(query || request.anchor);
  if (query) params.set("q", query);
  if (request.anchor) {
    params.set("anchorKind", request.anchor.kind);
    params.set("anchorId", request.anchor.id);
    if (request.anchor.lineageId) params.set("anchorLineageId", request.anchor.lineageId);
  }
  if (hasPayload || clampKnowledgeQueryTokenBudget(request.maxTokens) !== 1600) {
    params.set("maxTokens", String(clampKnowledgeQueryTokenBudget(request.maxTokens)));
  }
  if (request.from) params.set("from", request.from);
  if (demo) params.set("demo", "1");
  const queryString = params.toString();
  return queryString ? `/newsroom/search?${queryString}` : "/newsroom/search";
}

function focusNewsroomSearchForm() {
  if (typeof window === "undefined") return;
  const input = document.getElementById("newsroom-search-query");
  if (input instanceof HTMLElement) {
    input.focus();
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  window.dispatchEvent(new CustomEvent("papyrus:newsroom-search-focus"));
}

function resolveCurrentRouteAnchor(activeTab: NewsDeskTab): KnowledgeQueryAnchor | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  const segments = url.pathname.split("/").filter(Boolean);
  const detailId = segments[2] ? decodeURIComponent(segments[2]) : null;
  if (activeTab === "references" && detailId) return { kind: "reference", id: detailId, lineageId: detailId };
  if (activeTab === "messages" && detailId) return { kind: "message", id: detailId };
  if (activeTab === "assignments" && detailId) return { kind: "assignment", id: detailId };
  if (activeTab === "topics") {
    const category = url.searchParams.get("category")?.trim();
    if (category) return { kind: "category", id: category, lineageId: category };
  }
  if (activeTab === "concepts") {
    const node = url.searchParams.get("node")?.trim();
    if (node) return { kind: "semanticNode", id: node, lineageId: node };
    const category = url.searchParams.get("category")?.trim();
    if (category) return { kind: "category", id: category, lineageId: category };
  }
  return null;
}

function resolveKnowledgeQueryTarget(
  anchor: KnowledgeQueryAnchor | null | undefined,
  input: {
    assignments: AssignmentRecord[];
    categorys: CategorySteeringCategory[];
    messages: MessageRecord[];
    newsroomSections?: NewsroomSectionRecord[];
    references: ReferenceRecord[];
    semanticNodes: SemanticNodeRecord[];
  },
): KnowledgeQueryTarget | null {
  if (!anchor) return null;
  const anchorId = anchor.lineageId ?? anchor.id;
  if (anchor.kind === "reference") {
    const reference = input.references.find((entry) => (entry.lineageId ?? entry.id) === anchorId || entry.id === anchor.id);
    return {
      anchor: {
        kind: "reference",
        id: reference?.id ?? anchor.id,
        lineageId: reference?.lineageId ?? anchor.lineageId ?? anchor.id,
      },
      title: reference?.title ?? reference?.externalItemId ?? anchorId,
      subtitle: reference?.corpusId ?? null,
    };
  }
  if (anchor.kind === "message") {
    const message = input.messages.find((entry) => entry.id === anchor.id);
    return {
      anchor: { kind: "message", id: message?.id ?? anchor.id },
      title: message?.summary ?? "Stored message payload",
      subtitle: message?.messageKind ?? null,
    };
  }
  if (anchor.kind === "assignment") {
    const assignment = input.assignments.find((entry) => entry.id === anchor.id);
    return {
      anchor: { kind: "assignment", id: assignment?.id ?? anchor.id },
      title: assignment?.title ?? anchor.id,
      subtitle: assignment?.assignmentTypeKey ?? null,
    };
  }
  if (anchor.kind === "category") {
    const category = input.categorys.find((entry) => categoryLineageId(entry) === anchorId || entry.categoryKey === anchor.id || entry.id === anchor.id);
    return {
      anchor: {
        kind: "category",
        id: category?.id ?? category?.categoryKey ?? anchor.id,
        lineageId: category ? categoryLineageId(category) : (anchor.lineageId ?? anchor.id),
      },
      title: category?.displayName ?? anchorId,
      subtitle: category?.categoryKey ?? null,
    };
  }
  if (anchor.kind === "semanticNode") {
    const node = input.semanticNodes.find((entry) => (entry.lineageId ?? entry.id) === anchorId || entry.id === anchor.id || entry.nodeKey === anchor.id);
    return {
      anchor: {
        kind: "semanticNode",
        id: node?.id ?? anchor.id,
        lineageId: node?.lineageId ?? anchor.lineageId ?? anchor.id,
      },
      title: node?.displayName ?? node?.nodeKey ?? anchorId,
      subtitle: node?.nodeKind ?? null,
    };
  }
  if (anchor.kind === "newsroomSection") {
    const section = (input.newsroomSections ?? []).find((entry) => entry.id === anchor.id || entry.id === anchorId);
    return {
      anchor: { kind: "newsroomSection", id: section?.id ?? anchor.id, lineageId: section?.id ?? anchor.lineageId ?? anchor.id },
      title: section?.title ?? anchorId,
      subtitle: section?.type ?? null,
    };
  }
  return {
    anchor,
    title: anchorId,
    subtitle: null,
  };
}

function getNewsDeskTabHref(href: string, _demo?: boolean): string {
  return href;
}

function buildNewsroomDetailUrl(tab: "assignments" | "concepts" | "messages" | "references" | "topics", id: string | null): string {
  const encoded = id ? encodeURIComponent(id) : "";
  return id
    ? tab === "concepts"
      ? `/newsroom/concepts?node=${encoded}`
      : tab === "topics"
        ? `/newsroom/topics?category=${encoded}`
        : `/newsroom/${tab}/${encoded}`
    : `/newsroom/${tab}`;
}

function pushNewsroomDetailUrl(tab: "assignments" | "concepts" | "messages" | "references" | "topics", id: string | null, _demo?: boolean) {
  if (typeof window === "undefined") return;
  const url = buildNewsroomDetailUrl(tab, id);
  if (`${window.location.pathname}${window.location.search}` !== url) {
    window.history.pushState(null, "", url);
  }
}

function replaceNewsroomDetailUrl(tab: "assignments" | "concepts" | "messages" | "references" | "topics", id: string | null, _demo?: boolean) {
  if (typeof window === "undefined") return;
  const url = buildNewsroomDetailUrl(tab, id);
  if (`${window.location.pathname}${window.location.search}` !== url) {
    window.history.replaceState(null, "", url);
  }
}

function administrationPanelHref(panel: AdministrationPanel, demo?: boolean): string {
  return getNewsDeskTabHref(`/newsroom/administration/${panel}`, demo);
}

async function getNewsDeskActorLabel(): Promise<string> {
  try {
    const session = await fetchAuthSession();
    const payload = session.tokens?.idToken?.payload ?? session.tokens?.accessToken.payload ?? {};
    const claim = readTextClaim(payload.email)
      ?? readTextClaim(payload.name)
      ?? readTextClaim(payload["cognito:username"])
      ?? readTextClaim(payload.username)
      ?? readTextClaim(payload.sub);
    return claim ?? "Papyrus newsroom";
  } catch {
    return "Papyrus newsroom";
  }
}

function readTextClaim(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function NewsroomProgressBackLink({
  searchAction = null,
}: {
  searchAction?: { disabled: boolean; onPress: () => void } | null;
}) {
  return (
    <nav className="edition-progress edition-progress--newsroom" aria-label="Newsroom navigation">
      <Link className="edition-progress__button edition-progress__button--previous" href="/">
        <svg aria-hidden="true" className="edition-progress__icon" focusable="false" viewBox="0 0 10 10">
          <path d="M7.5 1 2.5 5 7.5 9Z" fill="currentColor" />
        </svg>
        Back to Papyrus
      </Link>
      {searchAction ? (
        <div className="edition-progress__trailing">
          <NewsroomConsoleProgressToggle />
          <button
            type="button"
            className="edition-progress__button edition-progress__button--next edition-progress__button--search"
            aria-label="Search knowledge base (semantic + ontology)"
            title="Search (semantic + ontology)"
            disabled={searchAction.disabled}
            onClick={searchAction.onPress}
          >
            <SearchMarkIcon />
          </button>
        </div>
      ) : (
        <div className="edition-progress__trailing">
          <NewsroomConsoleProgressToggle />
        </div>
      )}
    </nav>
  );
}

function NewsDeskAccessGate({ shell, showSectionTabs = false }: { shell: NewsDeskShellState | null; showSectionTabs?: boolean }) {
  const pathname = usePathname();
  const showRhythmOverlay = useNewsroomRhythmOverlay();
  const resolvedTheme = useResolvedPapyrusTheme();
  const drawerController = useNewsDeskDrawerController();
  const activeTab = inferNewsDeskTabFromPathname(pathname);
  const accessPhase = shell?.phase ?? "checkingAccess";

  return (
    <main
      className="site-shell news-desk-shell"
      data-news-desk-access={accessPhase}
      data-news-desk-drawer-docked={drawerController.isDocked ? "true" : "false"}
      data-news-desk-drawer-open={drawerController.open ? "true" : "false"}
      data-rhythm-overlay={showRhythmOverlay ? "true" : "false"}
    >
      <NewsroomProgressBackLink />
      <section className="scroll-edition news-desk-edition">
        <div className="paper-page paper-page--front paper-page--active">
          <article className="paper-page-content paper-page-content--front news-desk-page news-desk-page--gate" aria-labelledby="news-desk-access-title">
	            <header className="masthead news-desk-masthead">
	              <div className="masthead__rule" />
	              <h1 id="news-desk-access-title">
	                <span>NEWSROOM</span>
	              </h1>
		            <div className="masthead__meta" aria-label="Newsroom edition status">
	              <span><NewsDeskDrawerTrigger controller={drawerController} /></span>
	              <span aria-hidden="true" className="masthead__meta-placeholder">&nbsp;</span>
	              <span><Link className="news-desk-auth-control-link" href="/settings">Settings</Link></span>
	            </div>
	            </header>
            <NewsDeskDrawerPanel activeTab={activeTab} controller={drawerController} />
            {showSectionTabs ? (
              <nav className="news-desk-tabs" aria-label="Newsroom sections">
                {NEWS_DESK_TABS.map((tab) => (
                  <NewsDeskTabLink
                    key={tab.id}
                    active={false}
                    count={0}
                    countSlot={tab.id !== "administration"}
                    countVisible={false}
                    tab={tab}
                  />
                ))}
              </nav>
            ) : null}
            <section className="news-desk-access-panel" aria-live="polite" data-news-desk-access-phase={accessPhase}>
              <div className="news-desk-access-panel__copy" key={`copy-${accessPhase}`}>
                <p className="story-label">Access</p>
                <h2>{formatAccessTitle(shell)}</h2>
                <p>{formatAccessDetail(shell)}</p>
                {shell?.error ? <p className="news-desk-access-panel__error">{shell.error}</p> : null}
                <p className="news-desk-access-panel__auth">{formatAccessActionDetail(shell)}</p>
              </div>
            </section>
          </article>
        </div>
      </section>
    </main>
  );
}

function formatAccessTitle(state: NewsDeskShellState | null): string {
  if (!state || state.phase === "checkingAccess") return "Checking Desk Credentials";
  if (state.phase === "loadingDesk") return "Loading Newsroom Records";
  if (state.phase === "forbidden") return "Editor Role Required";
  if (state.phase === "error") return "Newsroom Unavailable";
  return "Editor Sign-In Required";
}

function formatAccessDetail(state: NewsDeskShellState | null): string {
  if (!state || state.phase === "checkingAccess") return "Papyrus is checking the current browser session before loading steering state.";
  if (state.phase === "loadingDesk") return "Papyrus verified the browser session and is loading private Newsroom records.";
  if (state.phase === "forbidden") return "This account is signed in, but the Cognito session does not include the editor or admin group.";
  if (state.phase === "error") return "Papyrus could not verify this editor session or load the private Newsroom data.";
  return "Sign in with an editor or admin account to inspect category, category tree, ontology, and graph steering.";
}

function formatAccessActionDetail(state: NewsDeskShellState | null): string {
  if (!state || state.phase === "checkingAccess") return "This should only take a moment. If it hangs, reload the page.";
  if (state.phase === "loadingDesk") return "Private records are loading from GraphQL. Large reference queues may take several seconds.";
  if (state.phase === "forbidden") return "Ask an admin to add this account to the editor or admin group, then sign out and back in.";
  if (state.phase === "error") return "Reload the page or check the local development console for the GraphQL error.";
  return "Use the login button above to authenticate with an editor or admin account.";
}

function SectionHeader({ title, detail }: { title: string; detail: string }) {
  const id = title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <header className="category-steering-section__header">
      <h2 id={`${id}-title`}>{title}</h2>
      <span>{detail}</span>
    </header>
  );
}

function TopicProposalQueue({
  disabled,
  proposals,
  referenceByAnyId,
  onAction,
  onEdit,
  onFocusTopic,
}: {
  disabled: boolean;
  proposals: CategorySteeringProposal[];
  referenceByAnyId: Map<string, ReferenceRecord>;
  onAction: (proposal: CategorySteeringProposal, action: ReviewAction) => void;
  onEdit: (proposal: CategorySteeringProposal) => void;
  onFocusTopic: (categoryKey: string) => void;
}) {
  const [statusFilter, setStatusFilter] = useState<string>("proposed");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const statusFiltered = useMemo(() => (
    proposals.filter((proposal) => {
      if (statusFilter === "all") return true;
      if (statusFilter === "reviewed") return proposal.status === "accepted" || proposal.status === "rejected";
      return proposal.status === statusFilter;
    })
  ), [proposals, statusFilter]);
  const availableKinds = useMemo(() => (
    Array.from(new Set(proposals.map((proposal) => proposal.proposalKind))).sort()
  ), [proposals]);
  const visible = useMemo(() => (
    statusFiltered.filter((proposal) => kindFilter === "all" || proposal.proposalKind === kindFilter)
  ), [kindFilter, statusFiltered]);

  return (
    <section className="category-steering-section" aria-label="Topic proposal review queue">
      <SectionHeader title="Topic Review Queue" detail={`${visible.length} visible / ${proposals.length} total`} />
      <p className="news-desk-topic-queue-note">
        Reject suppresses repeated proposals in future discovery for the same classifier/root scope. Merge consolidates topic intent under an accepted node. Delete/archive removes a node from active taxonomy scope for future child discovery.
      </p>
      <div className="news-desk-topic-queue-toolbar">
        <label>
          <span>Status</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="proposed">Proposed</option>
            <option value="deferred">Deferred</option>
            <option value="reviewed">Reviewed</option>
            <option value="all">All</option>
          </select>
        </label>
        <label>
          <span>Kind</span>
          <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}>
            <option value="all">All kinds</option>
            {availableKinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
          </select>
        </label>
      </div>
      <div className="category-steering-table-wrap">
        <table className="category-steering-table">
          <thead>
            <tr>
              <th>Proposal</th>
              <th>Kind</th>
              <th>Target root</th>
              <th>Status</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {visible.length ? visible.map((proposal) => {
              const targetRoot = proposal.targetCategoryKey ?? proposal.categoryKey ?? "";
              return (
                <tr data-topic-queue-proposal={proposal.id} key={proposal.id}>
                  <td>
                    <strong>{proposal.displayName ?? proposal.title}</strong>
                    <p>{proposal.summary ?? "No summary provided."}</p>
                    <ProposalEvidencePreview
                      proposal={proposal}
                      referenceByAnyId={referenceByAnyId}
                    />
                  </td>
                  <td>{proposal.proposalKind}</td>
                  <td>
                    {targetRoot ? (
                      <button
                        type="button"
                        className="news-desk-topic-link-button"
                        disabled={disabled}
                        onClick={() => onFocusTopic(targetRoot)}
                      >
                        {targetRoot}
                      </button>
                    ) : "n/a"}
                  </td>
                  <td><StatusPill status={proposal.status} /></td>
                  <td>
                    <ProposalReviewActions
                      disabled={disabled}
                      proposal={proposal}
                      onAction={onAction}
                      onEdit={onEdit}
                    />
                  </td>
                </tr>
              );
            }) : (
              <tr><td colSpan={5}>No proposals match the selected queue filters</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type ProposalEvidenceEntry = {
  id: string;
  title: string;
  href: string | null;
};

function ProposalEvidencePreview({
  proposal,
  referenceByAnyId,
}: {
  proposal: CategorySteeringProposal;
  referenceByAnyId: Map<string, ReferenceRecord>;
}) {
  const evidence = proposalEvidenceExamples(proposal, referenceByAnyId, 20);
  const count = proposalEvidenceCount(proposal);
  const targetTopic = proposal.targetCategoryKey ?? proposal.categoryKey ?? null;
  const referencesHref = targetTopic ? categoryDrilldownHref("references", targetTopic) : null;
  if (!count && !evidence.length && !referencesHref) return null;
  return (
    <div className="category-steering-evidence-preview">
      <div className="category-steering-evidence-preview__header">
        <strong>{count} evidence refs</strong>
        {referencesHref ? <Link href={referencesHref}>Open topic references</Link> : null}
      </div>
      {evidence.length ? (
        <div className="category-steering-evidence-chips">
          {evidence.map((entry) => (
            entry.href
              ? <Link href={entry.href} key={`${proposal.id}-${entry.id}`}>{entry.title}</Link>
              : <span key={`${proposal.id}-${entry.id}`}>{entry.title}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ProposalReviewActions({
  disabled,
  proposal,
  onAction,
  onEdit,
}: {
  disabled: boolean;
  proposal: CategorySteeringProposal;
  onAction: (proposal: CategorySteeringProposal, action: ReviewAction) => void;
  onEdit: (proposal: CategorySteeringProposal) => void;
}) {
  const acceptBlockedReason = proposalReviewActionBlockedReason(proposal, "accept");
  const editBlockedReason = proposalReviewActionBlockedReason(proposal, "edit");
  return (
    <div className="category-steering-proposal__actions" aria-label={`${proposal.title} review actions`}>
      <button
        type="button"
        data-review-action="accept"
        disabled={disabled || proposal.status === "accepted" || Boolean(acceptBlockedReason)}
        onClick={() => onAction(proposal, "accept")}
        title={acceptBlockedReason ?? undefined}
      >
        Accept
      </button>
      <button
        type="button"
        data-review-action="reject"
        disabled={disabled || proposal.status === "rejected"}
        onClick={() => onAction(proposal, "reject")}
      >
        Reject
      </button>
      <button
        type="button"
        data-review-action="defer"
        disabled={disabled || proposal.status === "deferred"}
        onClick={() => onAction(proposal, "defer")}
      >
        Defer
      </button>
      <button
        type="button"
        data-review-action="edit"
        disabled={disabled || proposal.status === "accepted" || Boolean(editBlockedReason)}
        onClick={() => onEdit(proposal)}
        title={editBlockedReason ?? undefined}
      >
        Edit
      </button>
    </div>
  );
}

function GenericProposalQueue({
  proposals,
  disabled,
  onAction,
  onEdit,
}: {
  proposals: CategorySteeringProposal[];
  disabled: boolean;
  onAction: (proposal: CategorySteeringProposal, action: ReviewAction) => void;
  onEdit: (proposal: CategorySteeringProposal) => void;
}) {
  return (
    <section className="category-steering-section" aria-labelledby="ontology-and-graph-proposals-title">
      <SectionHeader title="Ontology And Graph Wire" detail={`${proposals.length} generic notes`} />
      <div className="category-steering-table-wrap">
        <table className="category-steering-table">
          <thead>
            <tr>
              <th>Domain</th>
              <th>Kind</th>
              <th>Subject</th>
              <th>Relationship</th>
              <th>Status</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {proposals.length ? proposals.map((proposal) => (
              <tr key={proposal.id} data-generic-proposal-kind={proposal.proposalKind}>
                <td>{proposal.steeringDomain}</td>
                <td>{proposal.proposalKind}</td>
                <td>{formatGenericProposalSubject(proposal)}</td>
                <td>{proposal.relationshipType ?? "none"}</td>
                <td><StatusPill status={proposal.status} /></td>
                <td>
                  <ProposalReviewActions
                    disabled={disabled}
                    proposal={proposal}
                    onAction={onAction}
                    onEdit={onEdit}
                  />
                </td>
              </tr>
            )) : (
              <tr><td colSpan={6}>No category tree, ontology, or graph proposals</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AcceptedCategoryTreeSection({
  activeCategoryTree,
  canonicalCategorys,
  categoryByUid,
  categoryKeywords,
  disabled,
  graph,
  initialCategoryLineageId,
  onAction,
  onEdit,
  onCategorySave,
  onLexicalRuleCreate,
  proposals,
  lexicalSteeringRules,
  categoryTreeLoadError,
  categoryNodes,
}: {
  activeCategoryTree: CategorySteeringCategoryTree | null;
  canonicalCategorys: CategorySteeringCategory[];
  categoryByUid: Map<string, CategorySteeringCategory>;
  categoryKeywords: CategoryKeywordRecord[];
  disabled: boolean;
  graph: SemanticGraph;
  initialCategoryLineageId?: string | null;
  onAction: (proposal: CategorySteeringProposal, action: ReviewAction) => void;
  onEdit: (proposal: CategorySteeringProposal) => void;
  onCategorySave: (category: CategorySteeringCategory, update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">) => void;
  onLexicalRuleCreate: (draft: LexicalRuleDraft) => void;
  proposals: CategorySteeringProposal[];
  lexicalSteeringRules: LexicalSteeringRuleRecord[];
  categoryTreeLoadError: string | null;
  categoryNodes: CategorySteeringCategoryTreeNode[];
}) {
  const roots = buildCanonicalTopicRoots(canonicalCategorys, categoryNodes, proposals);
  const subcategoryCount = roots.reduce((count, root) => count + root.subcategorys.length, 0);
  const proposedSubcategoryCount = roots.reduce((count, root) => count + root.proposedSubcategorys.length, 0);
  const initialRootKey = selectInitialRootKey(roots, initialCategoryLineageId);
  const [selectedRootKey, setSelectedRootKey] = useState<string | null>(initialRootKey);
  const selectedRoot = roots.find((root) => root.category.categoryKey === selectedRootKey) ?? roots[0] ?? null;
  const initialFocusKey = selectInitialFocusKey(selectedRoot, initialCategoryLineageId);
  const [focusedCategoryKey, setFocusedCategoryKey] = useState<string | null>(initialFocusKey);
  const focusedNode = selectedRoot
    ? [categoryToCategoryTreeNode(selectedRoot.category), ...(selectedRoot.node ? [selectedRoot.node] : []), ...selectedRoot.subcategorys]
      .find((node) => node.categoryKey === focusedCategoryKey)
      ?? categoryToCategoryTreeNode(selectedRoot.category)
    : null;
  const detail = activeCategoryTree || roots.length
    ? `${roots.length} canonical / ${subcategoryCount} accepted subcategories / ${proposedSubcategoryCount} proposed`
    : categoryTreeLoadError
      ? "CategoryTree unavailable"
      : "Editor sign-in required";
  const editableCategory = focusedCategoryKey
    ? categoryByUid.get(focusedCategoryKey)
      ?? (selectedRoot?.category.categoryKey === focusedCategoryKey ? selectedRoot.category : undefined)
    : selectedRoot?.category;

  useEffect(() => {
    if (!roots.length) {
      setSelectedRootKey(null);
      setFocusedCategoryKey(null);
      return;
    }
    const nextRootKey = selectedRoot?.category.categoryKey ?? initialRootKey ?? roots[0].category.categoryKey;
    if (selectedRootKey !== nextRootKey) setSelectedRootKey(nextRootKey);
  }, [initialRootKey, roots, selectedRoot, selectedRootKey]);

  useEffect(() => {
    if (!selectedRoot) return;
    const validKeys = new Set([selectedRoot.category.categoryKey, ...selectedRoot.subcategorys.map((subcategory) => subcategory.categoryKey)]);
    if (!focusedCategoryKey || !validKeys.has(focusedCategoryKey)) {
      setFocusedCategoryKey(selectedRoot.category.categoryKey);
    }
  }, [focusedCategoryKey, selectedRoot]);

  return (
    <section className="category-steering-section category-steering-section--categoryTree" aria-labelledby="accepted-categoryTree-title">
      <SectionHeader title="Canonical Topics" detail={detail} />
      {categoryTreeLoadError ? (
        <div className="category-steering-alert" role="status">
          {categoryTreeLoadError}
        </div>
      ) : null}
      {!activeCategoryTree && !roots.length ? (
        <EmptyRow label="Accepted subcategories are visible to signed-in editors" />
      ) : (
        <div className="news-desk-topic-browser" data-news-desk-category-tree>
          <div className="news-desk-topic-browser__roots" aria-label="Canonical topic list">
            {roots.length ? roots.map((root) => {
              const rootNode = root.node ?? categoryToCategoryTreeNode(root.category);
              const relatedProposalCount = countRelatedCategoryTreeProposals(rootNode.categoryKey, root.subcategorys, proposals);
              const rootContext = buildTopicDrilldownContext(root, rootNode, categoryByUid);
              const rootReferenceCount = referencesForCategoryContext(graph, rootContext).length;
              const previewKeywords = keywordsForCategory(categoryKeywords, rootNode.categoryKey).slice(0, 4);
              const isSelected = selectedRoot?.category.categoryKey === root.category.categoryKey;
              return (
                <Link
                  aria-pressed={isSelected}
                  className="news-desk-topic-root-button"
                  data-selected={isSelected || undefined}
                  href={topicHref(rootNode.categoryKey)}
                  key={root.category.categoryKey}
	                  onClick={() => {
	                    setSelectedRootKey(root.category.categoryKey);
	                    setFocusedCategoryKey(root.category.categoryKey);
	                  }}
	                >
                  <span>{rootNode.shortTitle ?? deriveShortTitle(rootNode.displayName)}</span>
                  <strong>{rootNode.displayName}</strong>
                  <small>{rootReferenceCount} refs / {root.subcategorys.length} accepted / {root.proposedSubcategorys.length} proposed / {relatedProposalCount} notes</small>
	                  {previewKeywords.length ? (
	                    <em>{previewKeywords.map((keyword) => keyword.keyword).join(" / ")}</em>
	                  ) : null}
	                </Link>
              );
            }) : <EmptyRow label="No canonical roots available for category-tree display" />}
          </div>
          {selectedRoot ? (
            <>
              <CanonicalTopicDetail
                categoryByUid={categoryByUid}
                disabled={disabled}
                focusedCategoryKey={focusedCategoryKey}
                focusedNode={focusedNode}
                graph={graph}
                categoryKeywords={categoryKeywords}
                lexicalSteeringRules={lexicalSteeringRules}
                onAction={onAction}
                onEdit={onEdit}
                onFocusCategory={setFocusedCategoryKey}
                onLexicalRuleCreate={onLexicalRuleCreate}
                proposals={proposals}
                root={selectedRoot}
              />
              {editableCategory ? (
                <CategoryEditor category={editableCategory} disabled={disabled} onSave={onCategorySave} />
              ) : null}
            </>
          ) : null}
        </div>
      )}
    </section>
  );
}

type CanonicalTopicRoot = {
  category: CategorySteeringCategory;
  node?: CategorySteeringCategoryTreeNode;
  subcategorys: CategorySteeringCategoryTreeNode[];
  proposedSubcategorys: CategorySteeringProposal[];
};

function buildCanonicalTopicRoots(
  canonicalCategorys: CategorySteeringCategory[],
  categoryNodes: CategorySteeringCategoryTreeNode[],
  proposals: CategorySteeringProposal[],
): CanonicalTopicRoot[] {
  return canonicalCategorys
    .filter((category) => category.status === "accepted" && !category.parentCategoryKey && category.versionState !== "superseded")
    .map((category) => {
      const node = categoryNodes.find((candidate) => (
        candidate.categoryKey === category.categoryKey
        && !candidate.parentCategoryKey
        && candidate.status === "accepted"
        && candidate.versionState !== "superseded"
      ));
      const subcategorys = categoryNodes.filter((candidate) => (
        candidate.parentCategoryKey === category.categoryKey
        && candidate.status === "accepted"
        && candidate.versionState !== "superseded"
      ));
      return {
        category,
        node,
        subcategorys,
        proposedSubcategorys: getProposedSubcategoryProposals(category.categoryKey, proposals),
      };
    });
}

function semanticRelationKind(relation: SemanticRelationRecord): string {
  return relation.relationTypeKey ?? relation.predicate;
}

function isCurrentAcceptedReferenceRecord(reference: ReferenceRecord): boolean {
  return reference.versionState === "current" && reference.curationStatus === "accepted";
}

function buildEditableDraftName(displayName: string): string {
  return `${displayName.replace(/\s+Topic Sculpting Draft$/i, "").replace(/\s+Draft$/i, "").trim()} editing draft`;
}

function CanonicalTopicDetail({
  categoryByUid,
  categoryKeywords,
  disabled,
  focusedCategoryKey,
  focusedNode,
  graph,
  knowledgeQuery,
  lexicalSteeringRules,
  onAction,
  onEdit,
  onFocusCategory,
  onLexicalRuleCreate,
  proposals,
  referenceByAnyId = new Map<string, ReferenceRecord>(),
  root,
}: {
  categoryByUid: Map<string, CategorySteeringCategory>;
  categoryKeywords: CategoryKeywordRecord[];
  disabled: boolean;
  focusedCategoryKey: string | null;
  focusedNode: CategorySteeringCategoryTreeNode | null;
  graph: SemanticGraph;
  knowledgeQuery?: KnowledgeQueryControl;
  lexicalSteeringRules: LexicalSteeringRuleRecord[];
  onAction: (proposal: CategorySteeringProposal, action: ReviewAction) => void;
  onEdit: (proposal: CategorySteeringProposal) => void;
  onFocusCategory: (categoryKey: string) => void;
  onLexicalRuleCreate: (draft: LexicalRuleDraft) => void;
  proposals: CategorySteeringProposal[];
  referenceByAnyId?: Map<string, ReferenceRecord>;
  root: CanonicalTopicRoot;
}) {
  const rootNode = root.node ?? categoryToCategoryTreeNode(root.category);
  const relatedProposalCount = countRelatedCategoryTreeProposals(rootNode.categoryKey, root.subcategorys, proposals);
  const rootContext = buildTopicDrilldownContext(root, rootNode, categoryByUid);
  const rootReferenceCount = referencesForCategoryContext(graph, rootContext).length;
  const rootSeedExamples = evidenceExamplesForIds(compactArray(rootNode.seedItemIds), referenceByAnyId, 20);

  return (
    <article className="news-desk-topic-detail" data-news-desk-category-tree-root={rootNode.categoryKey}>
      <header className="news-desk-topic-detail__header">
        <div>
          <h3>{rootNode.displayName}</h3>
          <span>{rootNode.shortTitle ?? deriveShortTitle(rootNode.displayName)}</span>
        </div>
      </header>
      {knowledgeQuery ? <KnowledgeQueryStatus error={knowledgeQuery.error} loading={knowledgeQuery.loading} /> : null}
      {knowledgeQuery?.result ? (
        <KnowledgeQueryResultBlock result={knowledgeQuery.result} onClear={knowledgeQuery.clear} />
      ) : (
        <>
          <dl className="news-desk-topic-detail__stats">
            <div>
              <dt>References</dt>
              <dd>{rootReferenceCount}</dd>
            </div>
            <div>
              <dt>Accepted Subtopics</dt>
              <dd>{root.subcategorys.length}</dd>
            </div>
            <div>
              <dt>Proposed</dt>
              <dd>{root.proposedSubcategorys.length}</dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd>{relatedProposalCount}</dd>
            </div>
          </dl>
          {rootNode.subtitle ? <p className="category-steering-categoryTree-subtitle">{rootNode.subtitle}</p> : null}
          <p>{rootNode.description ?? "Accepted root category."}</p>
          <div className="category-steering-categoryTree-evidence">
            <span>{compactArray(rootNode.seedItemIds).length} seed refs</span>
            <span>{compactArray(rootNode.holdoutItemIds).length} holdout refs</span>
            <span>{rootNode.categoryKey}</span>
          </div>
          {rootSeedExamples.length ? (
            <div className="category-steering-evidence-preview">
              <div className="category-steering-evidence-preview__header">
                <strong>Top seed examples</strong>
                <Link href={categoryDrilldownHref("references", rootNode.categoryKey)}>View all references</Link>
              </div>
              <div className="category-steering-evidence-chips">
                {rootSeedExamples.map((entry) => (
                  entry.href
                    ? <Link href={entry.href} key={`${rootNode.categoryKey}-${entry.id}`}>{entry.title}</Link>
                    : <span key={`${rootNode.categoryKey}-${entry.id}`}>{entry.title}</span>
                ))}
              </div>
            </div>
          ) : null}

          <div className="news-desk-topic-detail__body">
            <div className="news-desk-topic-detail__subtopics">
              <p className="category-steering-subcategory-list__label">Accepted Subtopics</p>
              <div className="news-desk-topic-subtopic-buttons">
                {(() => {
                  const rootLineageId = categoryLineageId(rootNode);
                  return (
                    <TopicFocusButton
                      active={focusedCategoryKey === rootNode.categoryKey}
                      conceptCount={semanticNodesForCategoryContext(graph, buildTopicDrilldownContext(root, rootNode, categoryByUid)).length}
                      count={referencesForCategoryContext(graph, buildTopicDrilldownContext(root, rootNode, categoryByUid)).length}
                      dataCategoryKey={rootNode.categoryKey}
                      label={rootNode.shortTitle ?? deriveShortTitle(rootNode.displayName)}
                      lineageId={rootLineageId}
                      rootCategoryKey={rootNode.categoryKey}
                      title={rootNode.displayName}
                      onClick={() => onFocusCategory(rootNode.categoryKey)}
                    />
                  );
                })()}
                {root.subcategorys.length ? root.subcategorys.map((subcategory) => (
                  (() => {
                    const subcategoryLineageId = categoryLineageId(subcategory);
                    return (
                      <TopicFocusButton
                        active={focusedCategoryKey === subcategory.categoryKey}
                        conceptCount={semanticNodesForCategoryContext(graph, buildTopicDrilldownContext(root, subcategory, categoryByUid)).length}
                        count={referencesForCategoryContext(graph, buildTopicDrilldownContext(root, subcategory, categoryByUid)).length}
                        dataCategoryKey={subcategory.categoryKey}
                        key={subcategory.id}
                        label={subcategory.shortTitle ?? deriveShortTitle(subcategory.displayName)}
                        lineageId={subcategoryLineageId}
                        rootCategoryKey={rootNode.categoryKey}
                        title={subcategory.displayName}
                        onClick={() => onFocusCategory(subcategory.categoryKey)}
                      />
                    );
                  })()
                )) : null}
              </div>
              {!root.subcategorys.length ? <EmptyRow label="No accepted subtopics under this root" /> : null}

              {root.proposedSubcategorys.length ? (
                <div className="category-steering-subcategory-list category-steering-subcategory-list--proposed">
                  <p className="category-steering-subcategory-list__label">Proposed Subtopics</p>
                  {root.proposedSubcategorys.map((proposal) => (
                    <article className="category-steering-subcategory category-steering-subcategory--proposed" data-news-desk-proposed-subcategory={proposal.categoryKey ?? proposal.id} key={proposal.id}>
                      <h4>{proposal.displayName ?? proposal.title}</h4>
                      <span>{proposal.shortTitle ?? deriveShortTitle(proposal.displayName ?? proposal.title)}</span>
                      {proposal.subtitle ? <p className="category-steering-categoryTree-subtitle">{proposal.subtitle}</p> : null}
                      <p>{proposal.description ?? proposal.summary ?? "Candidate subtopic from steering proposals."}</p>
                      <div className="category-steering-categoryTree-evidence">
                        <span>{proposal.proposalKind}</span>
                        <span>{proposal.status}</span>
                        <span>{proposalEvidenceCount(proposal)} evidence refs</span>
                        <span>{proposal.categoryKey ?? "new category"}</span>
                      </div>
                      <ProposalEvidencePreview
                        proposal={proposal}
                        referenceByAnyId={referenceByAnyId}
                      />
                      <ProposalReviewActions
                        disabled={disabled}
                        proposal={proposal}
                        onAction={onAction}
                        onEdit={onEdit}
                      />
                    </article>
                  ))}
                </div>
              ) : null}
            </div>

            <TopicSemanticContext
              categoryContext={focusedNode ? buildTopicDrilldownContext(root, focusedNode, categoryByUid) : rootContext}
              categoryKeywords={categoryKeywords}
              disabled={disabled}
              graph={graph}
              lexicalSteeringRules={lexicalSteeringRules}
              node={focusedNode ?? rootNode}
              onLexicalRuleCreate={onLexicalRuleCreate}
            />
          </div>
        </>
      )}
    </article>
  );
}

function TopicFocusButton({
  active,
  conceptCount,
  count,
  dataCategoryKey,
  label,
  lineageId,
  onClick,
  rootCategoryKey,
  title,
}: {
  active: boolean;
  conceptCount: number;
  count: number;
  dataCategoryKey?: string;
  label: string;
  lineageId: string;
  onClick: () => void;
  rootCategoryKey: string;
  title: string;
}) {
  return (
    <div className="news-desk-topic-focus-row" data-selected={active || undefined}>
      <Link
        className="news-desk-topic-focus-button"
        data-news-desk-subcategory={dataCategoryKey}
        data-selected={active || undefined}
        href={topicHref(rootCategoryKey, dataCategoryKey)}
        onClick={onClick}
      >
        <strong>{label}</strong>
        <span>{title}</span>
        <small>{count} refs / {conceptCount} concepts</small>
      </Link>
      <div className="news-desk-topic-focus-row__actions" aria-label={`${title} drill-down links`}>
        <Link href={topicHref(rootCategoryKey, dataCategoryKey)}>Topic page</Link>
        <Link href={categoryDrilldownHref("references", dataCategoryKey ?? lineageId)}>References</Link>
        <Link href={categoryDrilldownHref("concepts", dataCategoryKey ?? lineageId)}>Concepts</Link>
      </div>
    </div>
  );
}

function TopicSemanticContext({
  categoryContext,
  categoryKeywords,
  disabled,
  graph,
  lexicalSteeringRules,
  node,
  onLexicalRuleCreate,
}: {
  categoryContext: CategoryDrilldownContext;
  categoryKeywords: CategoryKeywordRecord[];
  disabled: boolean;
  graph: SemanticGraph;
  lexicalSteeringRules: LexicalSteeringRuleRecord[];
  node: CategorySteeringCategoryTreeNode;
  onLexicalRuleCreate: (draft: LexicalRuleDraft) => void;
}) {
  const lineageId = categoryLineageId(node);
  const [referencePage, setReferencePage] = useState(0);
  const references = useMemo(() => sortReferenceSummariesByRecency(referencesForCategoryContext(graph, categoryContext)), [categoryContext, graph]);
  const pageCount = Math.max(1, Math.ceil(references.length / TOPIC_REFERENCE_PAGE_SIZE));
  const currentPage = Math.min(referencePage, pageCount - 1);
  const visibleReferences = references.slice(currentPage * TOPIC_REFERENCE_PAGE_SIZE, (currentPage + 1) * TOPIC_REFERENCE_PAGE_SIZE);
  const concepts = uniqueSemanticSummaries(
    semanticNodesForCategoryContext(graph, categoryContext),
  ).slice(0, 8);
  const neighborGroups = uniqueNeighborGroupsForCategoryContext(graph, categoryContext);

  useEffect(() => {
    setReferencePage(0);
  }, [lineageId]);

  return (
    <aside className="news-desk-topic-context" data-news-desk-topic-context={node.categoryKey}>
      <p className="story-label">Selected Topic</p>
      <h4>{node.displayName}</h4>
      {node.subtitle ? <p className="category-steering-categoryTree-subtitle">{node.subtitle}</p> : null}
      <p>{node.description ?? "No description imported for this topic."}</p>
      <div className="news-desk-topic-context__stats" aria-label="Selected topic reference counts">
        <div>
          <span>{categoryContext.includeDescendants ? "References including subtopics" : "References"}</span>
          <strong>{references.length}</strong>
        </div>
        <div>
          <span>Seed</span>
          <strong>{compactArray(node.seedItemIds).length}</strong>
        </div>
        <div>
          <span>Holdout</span>
          <strong>{compactArray(node.holdoutItemIds).length}</strong>
        </div>
      </div>
      <TopicReferencePanel
        currentPage={currentPage}
        includeDescendants={categoryContext.includeDescendants}
        node={node}
        pageCount={pageCount}
        references={references}
        visibleReferences={visibleReferences}
        onNext={() => setReferencePage((value) => Math.min(value + 1, pageCount - 1))}
        onPrevious={() => setReferencePage((value) => Math.max(value - 1, 0))}
      />
      <TopicKeywordsPanel
        categorySetId={node.categorySetId}
        categoryKey={node.categoryKey}
        classifierId={null}
        corpusId={node.corpusId}
        disabled={disabled}
        keywords={keywordsForCategory(categoryKeywords, node.categoryKey)}
        rules={lexicalSteeringRules}
        onLexicalRuleCreate={onLexicalRuleCreate}
      />
      <div className="news-desk-topic-context__block">
        <header>
          <strong>Associated Concepts</strong>
          <span>{concepts.length}</span>
        </header>
        {concepts.length ? concepts.map((concept) => (
          <Link href={concept.href} key={concept.lineageId}>
            <span>{concept.subtitle ?? "concept"}</span>
            <strong>{concept.label}</strong>
          </Link>
        )) : <EmptyRow label="No graph concepts attached yet" />}
        <Link className="news-desk-topic-reference-ledger-link" href={categoryDrilldownHref("concepts", node.categoryKey)}>
          View graph concepts
        </Link>
      </div>
      <NeighborGroups groups={neighborGroups} />
    </aside>
  );
}

function TopicReferencePanel({
  currentPage,
  includeDescendants,
  node,
  onNext,
  onPrevious,
  pageCount,
  references,
  visibleReferences,
}: {
  currentPage: number;
  includeDescendants: boolean;
  node: CategorySteeringCategoryTreeNode;
  onNext: () => void;
  onPrevious: () => void;
  pageCount: number;
  references: SemanticObjectSummary[];
  visibleReferences: SemanticObjectSummary[];
}) {
  return (
    <section className="news-desk-topic-reference-panel" data-news-desk-topic-references={node.categoryKey}>
      <header>
        <div>
          <p className="story-label">Reference Ledger</p>
          <h5>References In This Topic</h5>
        </div>
        <span>{references.length}</span>
      </header>
      {includeDescendants ? <p className="news-desk-topic-reference-panel__note">Including accepted subtopics.</p> : null}
      {visibleReferences.length ? (
        <div className="news-desk-topic-reference-list">
          {visibleReferences.map((reference) => (
            <Link className="news-desk-topic-reference-link" href={reference.href} key={reference.lineageId}>
              <span>{formatReferenceSummaryDate(reference)} / {reference.subtitle ?? "reference"}</span>
              <strong>{reference.label}</strong>
            </Link>
          ))}
        </div>
      ) : (
        <EmptyRow label="No classified references are attached to this topic yet. Run the curation cycle after importing projections." />
      )}
      {references.length > TOPIC_REFERENCE_PAGE_SIZE ? (
        <ReferencePager
          onNext={onNext}
          onPrevious={onPrevious}
          page={currentPage}
          pageCount={pageCount}
        />
      ) : null}
      {references.length ? (
        <Link className="news-desk-topic-reference-ledger-link" href={categoryDrilldownHref("references", node.categoryKey)}>
          View all references
        </Link>
      ) : null}
    </section>
  );
}

function TopicKeywordsPanel({
  categoryKey,
  categorySetId,
  classifierId,
  corpusId,
  disabled,
  keywords,
  rules,
  onLexicalRuleCreate,
}: {
  categoryKey: string;
  categorySetId: string;
  classifierId?: string | null;
  corpusId: string;
  disabled: boolean;
  keywords: CategoryKeywordRecord[];
  rules: LexicalSteeringRuleRecord[];
  onLexicalRuleCreate: (draft: LexicalRuleDraft) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [manualTerm, setManualTerm] = useState("");
  const activeIgnoredTerms = useMemo(() => ignoredTermSet(rules, { categorySetId, corpusId, classifierId, categoryKey }, false), [categoryKey, categorySetId, classifierId, corpusId, rules]);
  const archivedIgnoredTerms = useMemo(() => ignoredTermSet(rules, { categorySetId, corpusId, classifierId, categoryKey }, true), [categoryKey, categorySetId, classifierId, corpusId, rules]);
  const activeRules = rules.filter((rule) => rule.ruleKind === "ignored_keyword" && rule.status === "active");
  const archivedRules = rules.filter((rule) => rule.ruleKind === "ignored_keyword" && rule.status !== "active");
  const visibleKeywords = showAll ? keywords : keywords.slice(0, 14);

  function createRule(term: string, scope: LexicalRuleScope = "publication", note?: string) {
    const normalized = normalizeKeywordTerm(term);
    if (!normalized) return;
    onLexicalRuleCreate({
      term,
      scope,
      corpusId: scope === "corpus" || scope === "classifier" || scope === "category" ? corpusId : null,
      classifierId: scope === "classifier" || scope === "category" ? classifierId : null,
      categorySetId: scope === "category" ? categorySetId : null,
      categoryKey: scope === "category" ? categoryKey : null,
      note,
    });
  }

  return (
    <div className="news-desk-topic-context__block news-desk-topic-keywords" data-news-desk-topic-keywords={categoryKey}>
      <header>
        <strong>Topic Keywords</strong>
        <span>{keywords.length}</span>
      </header>
      <div className="news-desk-keyword-controls">
        <label>
          <span>Ignore term</span>
          <input
            type="text"
            value={manualTerm}
            onChange={(event) => setManualTerm(event.target.value)}
            placeholder="et, al, boilerplate"
          />
        </label>
        <button
          type="button"
          disabled={disabled || !normalizeKeywordTerm(manualTerm)}
          onClick={() => {
            createRule(manualTerm, "publication", "Manual lexical steering from Newsroom.");
            setManualTerm("");
          }}
        >
          Ignore
        </button>
      </div>
      {visibleKeywords.length ? (
        <div className="news-desk-keyword-list">
          {visibleKeywords.map((keyword) => {
            const isIgnored = activeIgnoredTerms.has(keyword.normalizedKeyword);
            const wasIgnored = archivedIgnoredTerms.has(keyword.normalizedKeyword);
            return (
              <div
                className="news-desk-keyword-row"
                data-ignored={isIgnored || undefined}
                data-archived-ignored={wasIgnored || undefined}
                key={keyword.id}
              >
                <span>{keyword.rank ?? "-"}</span>
                <strong>{keyword.keyword}</strong>
                <small>{keyword.weight != null ? keyword.weight.toFixed(3) : keyword.source}</small>
                <button
                  type="button"
                  disabled={disabled || isIgnored}
                  onClick={() => createRule(keyword.keyword, "publication", `Ignored from topic ${categoryKey}.`)}
                >
                  {isIgnored ? "Ignored" : "Ignore"}
                </button>
              </div>
            );
          })}
        </div>
      ) : <EmptyRow label="No keyword evidence imported for this topic yet" />}
      {keywords.length > visibleKeywords.length ? (
        <button className="news-desk-keyword-more" type="button" onClick={() => setShowAll(true)}>
          Show all {keywords.length} keywords
        </button>
      ) : showAll && keywords.length > 14 ? (
        <button className="news-desk-keyword-more" type="button" onClick={() => setShowAll(false)}>
          Show fewer keywords
        </button>
      ) : null}
      <details className="news-desk-ignored-terms" open={activeRules.length > 0}>
        <summary>{activeRules.length} active ignored terms</summary>
        <div>
          {activeRules.slice(0, 24).map((rule) => (
            <span key={rule.id}>{rule.term} <small>{rule.scope}</small></span>
          ))}
          {!activeRules.length ? <span>No active lexical rules</span> : null}
        </div>
      </details>
      {archivedRules.length ? (
        <label className="news-desk-keyword-toggle">
          <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
          <span>Show archived ignored terms</span>
        </label>
      ) : null}
      {showArchived ? (
        <div className="news-desk-ignored-terms__archive">
          {archivedRules.map((rule) => <span key={rule.id}>{rule.term} <small>{rule.scope}</small></span>)}
        </div>
      ) : null}
    </div>
  );
}

function ReferenceListControls({
  label,
  onNext,
  onPrevious,
  onQueryChange,
  onStatusChange,
  page,
  pageCount,
  query,
  status,
}: {
  label: string;
  onNext: () => void;
  onPrevious: () => void;
  onQueryChange: (query: string) => void;
  onStatusChange: (status: string) => void;
  page: number;
  pageCount: number;
  query: string;
  status: string;
}) {
  return (
    <div className="news-desk-reference-controls">
      <label>
        <span>Search references</span>
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Title, source path, author, item id"
        />
      </label>
      <label>
        <span>Curation status</span>
        <select value={status} onChange={(event) => onStatusChange(event.target.value)}>
          <option value="">All reference records</option>
          <option value="pending">Prospects</option>
          <option value="accepted">Accepted evidence</option>
          <option value="rejected">Scope rejections</option>
          <option value="archived">Archived references</option>
        </select>
      </label>
      <div>
        <span>{label}</span>
        <ReferencePager onNext={onNext} onPrevious={onPrevious} page={page} pageCount={pageCount} />
      </div>
    </div>
  );
}

function ReferencePager({
  onNext,
  onPrevious,
  page,
  pageCount,
}: {
  onNext: () => void;
  onPrevious: () => void;
  page: number;
  pageCount: number;
}) {
  return (
    <div className="news-desk-reference-pager">
      <button type="button" disabled={page <= 0} onClick={onPrevious}>Previous</button>
      <span>Page {page + 1} / {pageCount}</span>
      <button type="button" disabled={page >= pageCount - 1} onClick={onNext}>Next</button>
    </div>
  );
}

function ReferenceRow({ active, reference }: { active?: boolean; reference: ReferenceRecord }) {
  const lineageId = reference.lineageId ?? reference.id;
  const date = formatReferenceDate(reference);
  const processingStatus = resolveReferenceProcessingStatus(reference);
  const curationStatus = reference.curationStatus ?? "pending";
  return (
    <a
      className={`news-desk-object-row${active ? " news-desk-object-row--active" : ""}`}
      data-reference-lineage={lineageId}
      href={newsDeskHrefForSemanticObject("reference", lineageId)}
    >
      <strong>{reference.title ?? reference.externalItemId}</strong>
      <span>{processingStatus} / {curationStatus} / {date} / {reference.mediaType ?? "metadata"} / {reference.storagePath ?? reference.sourceUri ?? "no file path"}</span>
    </a>
  );
}

function resolveReferenceProcessingStatus(
  reference: ReferenceRecord,
  attachments: ReferenceAttachmentRecord[] = [],
): ReferenceProcessingStatus {
  const metadata = metadataRecord(reference.metadata);
  const explicit = normalizeMetadataString(metadata?.processingStatus);
  if (explicit === "created" || explicit === "processable" || explicit === "processed" || explicit === "blocked") {
    return explicit;
  }
  const lineageId = reference.lineageId ?? reference.id;
  const referenceAttachments = attachments.filter((attachment) => (
    attachment.referenceId === reference.id || attachment.referenceLineageId === lineageId
  ));
  const hasExtractedText = referenceAttachments.some((attachment) => (
    attachment.role === "extracted_text" && Boolean(attachment.storagePath || attachment.sourceUri)
  ));
  if (hasExtractedText) return "processed";
  const hasSource = Boolean(reference.sourceUri || reference.storagePath)
    || referenceAttachments.some((attachment) => attachment.role === "source" && Boolean(attachment.storagePath || attachment.sourceUri));
  if (hasSource) return "processable";
  return "created";
}

function isReferenceProcessed(
  reference: ReferenceRecord,
  attachments: ReferenceAttachmentRecord[] = [],
): boolean {
  const status = resolveReferenceProcessingStatus(reference, attachments);
  return status === "processed" || status === "blocked";
}

function formatGenericProposalSubject(proposal: CategorySteeringProposal): string {
  const parts = [
    proposal.categoryKey,
    proposal.graphEntityId,
    proposal.targetCategoryKey ? `-> ${proposal.targetCategoryKey}` : null,
    proposal.displayName,
  ].filter(Boolean);
  return parts.join(" ") || "unmapped";
}

function proposalReviewActionBlockedReason(proposal: CategorySteeringProposal, action: ReviewAction): string | null {
  if ((action === "accept" || action === "edit") && TOPIC_PROPOSAL_BLOCKED_APPLY_KINDS.has(proposal.proposalKind)) {
    return `${proposal.proposalKind} apply is not implemented yet.`;
  }
  return null;
}

function assertReviewMutationSucceeded(response: CategoryReviewResponse, proposalId: string): NonNullable<CategoryReviewResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Review was not saved for ${proposalId}.`);
  }
  if (response.data.proposalId && response.data.proposalId !== proposalId) {
    throw new Error(`Review response did not match proposal ${proposalId}.`);
  }
  if (!response.data.decisionId) {
    throw new Error(`Review saved no decision audit row for ${proposalId}.`);
  }
  return response.data;
}

function assertReferenceReviewMutationSucceeded(response: ReferenceReviewResponse, referenceId: string): NonNullable<ReferenceReviewResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Reference curation review was not saved for ${referenceId}.`);
  }
  if (response.data.referenceId && response.data.referenceId !== referenceId) {
    throw new Error(`Reference review response did not match ${referenceId}.`);
  }
  if (!response.data.messageId || !response.data.relationId) {
    throw new Error(`Reference review saved without commentary audit rows for ${referenceId}.`);
  }
  return response.data;
}

function assertReferenceQualityMutationSucceeded(
  response: ReferenceQualityResponse,
  referenceId: string,
  rating: number,
): NonNullable<ReferenceQualityResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Reference quality rating was not saved for ${referenceId}.`);
  }
  if (response.data.referenceId && response.data.referenceId !== referenceId) {
    throw new Error(`Reference quality response did not match ${referenceId}.`);
  }
  if (typeof response.data.rating === "number" && response.data.rating !== rating) {
    throw new Error(`Reference quality response returned ${response.data.rating}, expected ${rating}.`);
  }
  return response.data;
}

function assertReferenceInsightMutationSucceeded(
  response: ReferenceInsightResponse,
  referenceId: string,
): NonNullable<ReferenceInsightResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Reference insight was not saved for ${referenceId}.`);
  }
  if (response.data.referenceId && response.data.referenceId !== referenceId) {
    throw new Error(`Reference insight response did not match ${referenceId}.`);
  }
  if (!response.data.messageId || !response.data.relationId) {
    throw new Error(`Reference insight saved without required audit relations for ${referenceId}.`);
  }
  return response.data;
}

function assertReferenceMoveCorpusMutationSucceeded(
  response: ReferenceCorpusMoveResponse,
  referenceId: string,
  corpusId: string,
): NonNullable<ReferenceCorpusMoveResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Reference corpus move was not saved for ${referenceId}.`);
  }
  if (response.data.referenceId && response.data.referenceId !== referenceId) {
    throw new Error(`Reference corpus move response did not match ${referenceId}.`);
  }
  if (response.data.corpusId && response.data.corpusId !== corpusId) {
    throw new Error(`Reference corpus move response returned ${response.data.corpusId}, expected ${corpusId}.`);
  }
  return response.data;
}

function assertReferenceCurationStartMutationSucceeded(
  response: ReferenceCurationStartResponse,
  referenceId: string,
): NonNullable<ReferenceCurationStartResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Reference curation start failed for ${referenceId}.`);
  }
  if (response.data.referenceId && response.data.referenceId !== referenceId) {
    throw new Error(`Reference curation start response did not match ${referenceId}.`);
  }
  if (!response.data.assignmentId) {
    throw new Error(`Reference curation start returned no assignmentId for ${referenceId}.`);
  }
  return response.data;
}

function assertReferenceCurationStatusQuerySucceeded(
  response: ReferenceCurationStatusResponse,
  assignmentId: string,
): NonNullable<ReferenceCurationStatusResponse["data"]> {
  if (response.errors?.length) {
    throw new Error(response.errors.map(formatGraphQLError).join("; "));
  }
  if (!response.data?.ok) {
    throw new Error(`Reference curation status failed for ${assignmentId}.`);
  }
  if (response.data.assignmentId && response.data.assignmentId !== assignmentId) {
    throw new Error(`Reference curation status response did not match ${assignmentId}.`);
  }
  return response.data;
}

function referenceReasonLabel(code: ReferenceRejectionReasonCode): string {
  return code.replaceAll("_", " ");
}

function referenceLedgerLabel(status: string): string {
  if (status === "__exclude_pending") return "reviewed references";
  if (status === "pending") return "reference prospects";
  if (status === "accepted") return "accepted references";
  if (status === "rejected") return "rejected references";
  if (status === "archived") return "archived references";
  return "reference records";
}

function countReferencesByStatus(references: ReferenceRecord[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const reference of references) {
    const status = normalizeReferenceStatus(reference.curationStatus);
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

function countReferencesByProcessing(
  references: ReferenceRecord[],
  attachments: ReferenceAttachmentRecord[],
): { processed: number; unprocessed: number } {
  let processed = 0;
  let unprocessed = 0;
  for (const reference of references) {
    if (isReferenceProcessed(reference, attachments)) {
      processed += 1;
    } else {
      unprocessed += 1;
    }
  }
  return { processed, unprocessed };
}

function countMessagesBy(messages: MessageRecord[], key: "messageKind" | "messageDomain" | "status"): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const message of messages) {
    const value = message[key]?.trim() || "unknown";
    counts[value] = (counts[value] ?? 0) + 1;
  }
  return counts;
}

function countSemanticNodesByKind(nodes: SemanticNodeRecord[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const node of nodes) {
    const value = node.nodeKind?.trim() || "unknown";
    counts[value] = (counts[value] ?? 0) + 1;
  }
  return counts;
}

function countSemanticNodesByStatus(nodes: SemanticNodeRecord[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const node of nodes) {
    const value = node.status?.trim() || "unknown";
    counts[value] = (counts[value] ?? 0) + 1;
  }
  return counts;
}

function sortedCountOptions(counts: Record<string, number>): Array<{ key: string; count: number }> {
  return Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => ({ key, count }))
    .sort((left, right) => {
      const countDiff = right.count - left.count;
      if (countDiff !== 0) return countDiff;
      return left.key.localeCompare(right.key);
    });
}

function assertNoGraphQLErrors(errors?: unknown[] | null) {
  if (!errors?.length) return;
  throw new Error(errors.map((error) => formatGraphQLError(error as { message?: string | null } | string | null)).join("; "));
}

function formatGraphQLError(error: { message?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  return error?.message ?? "GraphQL mutation failed.";
}

function selectActiveCategoryTree(
  categoryTrees: CategorySteeringCategoryTree[],
  categorySetId: string | null,
  corpusId: string | null,
): CategorySteeringCategoryTree | null {
  const candidates = categoryTrees.filter((categoryTree) => (
    categoryTree.status !== "deprecated"
    && categoryTree.status !== "superseded"
    && categoryTree.versionState !== "superseded"
  ));
  const matchingCategorySet = categorySetId ? candidates.filter((categoryTree) => categoryTree.id === categorySetId) : candidates;
  const matchingCorpus = corpusId ? candidates.filter((categoryTree) => categoryTree.corpusId === corpusId) : candidates;
  return matchingCategorySet.find(isCurrentCategorySet)
    ?? matchingCorpus.find(isCurrentCategorySet)
    ?? candidates.find(isCurrentCategorySet)
    ?? null;
}

function categoryToCategoryTreeNode(category: CategorySteeringCategory): CategorySteeringCategoryTreeNode {
  return {
    id: category.id,
    lineageId: category.lineageId ?? category.id,
    versionNumber: category.versionNumber,
    previousVersionId: category.previousVersionId,
    versionState: category.versionState,
    versionCreatedAt: category.versionCreatedAt,
    versionCreatedBy: category.versionCreatedBy,
    changeReason: category.changeReason,
    contentHash: category.contentHash,
    categorySetId: category.categorySetId,
    corpusId: category.corpusId,
    categoryKey: category.categoryKey,
    parentCategoryId: category.parentCategoryId,
    parentCategoryKey: category.parentCategoryKey,
    displayName: category.displayName,
    shortTitle: category.shortTitle,
    subtitle: category.subtitle,
    description: category.description,
    aliases: category.aliases,
    status: category.status,
    seedItemIds: category.seedItemIds,
    holdoutItemIds: category.holdoutItemIds,
    rank: category.rank,
    depth: category.depth,
    isPinned: category.isPinned,
    importRunId: category.importRunId,
    updatedAt: category.updatedAt,
  };
}

function categoryTreeNodeToCategory(node: CategorySteeringCategoryTreeNode): CategorySteeringCategory {
  return {
    id: node.id,
    lineageId: node.lineageId,
    versionNumber: node.versionNumber,
    previousVersionId: node.previousVersionId,
    versionState: node.versionState,
    versionCreatedAt: node.versionCreatedAt,
    versionCreatedBy: node.versionCreatedBy,
    changeReason: node.changeReason,
    contentHash: node.contentHash,
    categorySetId: node.categorySetId,
    corpusId: node.corpusId,
    categoryKey: node.categoryKey,
    parentCategoryId: node.parentCategoryId,
    parentCategoryKey: node.parentCategoryKey,
    displayName: node.displayName,
    shortTitle: node.shortTitle,
    subtitle: node.subtitle,
    description: node.description,
    aliases: node.aliases,
    status: node.status,
    seedItemIds: node.seedItemIds,
    holdoutItemIds: node.holdoutItemIds,
    rank: node.rank,
    depth: node.depth,
    isPinned: node.isPinned,
    importRunId: node.importRunId,
    updatedAt: node.updatedAt,
  };
}

function mergeCategoryRecords(
  categorys: CategorySteeringCategory[],
  categoryNodes: CategorySteeringCategoryTreeNode[],
): CategorySteeringCategory[] {
  const records = new Map<string, CategorySteeringCategory>();
  for (const category of [...categorys, ...categoryNodes]) {
    records.set(category.id, category);
  }
  return Array.from(records.values());
}

function selectAcceptedCategoriesForDoctrine({
  categorys,
  categoryNodes,
  categorySetId,
}: {
  categorys: CategorySteeringCategory[];
  categoryNodes: CategorySteeringCategoryTreeNode[];
  categorySetId: string | null;
}): DoctrineCategory[] {
  const categoryByKey = new Map(categorys.map((category) => [category.categoryKey, category]));
  const matchesCategorySet = (categorySet: string) => !categorySetId || categorySet === categorySetId;
  return categoryNodes
    .filter((node) => (
      matchesCategorySet(node.categorySetId)
      && node.status === "accepted"
      && node.versionState !== "superseded"
    ))
    .map((node) => {
      const category = categoryByKey.get(node.categoryKey);
      return {
        ...node,
        id: category?.id ?? node.id,
        lineageId: category?.lineageId ?? node.lineageId ?? node.id,
        categorySetId: category?.categorySetId ?? node.categorySetId,
        categoryKey: node.categoryKey,
        displayName: category?.displayName ?? node.displayName,
        shortTitle: category?.shortTitle ?? node.shortTitle,
        rank: category?.rank ?? node.rank,
        depth: node.depth ?? category?.depth ?? 0,
      };
    });
}

function keywordsForCategory(keywords: CategoryKeywordRecord[], categoryKey: string): CategoryKeywordRecord[] {
  return keywords
    .filter((keyword) => keyword.categoryKey === categoryKey)
    .sort((left, right) => {
      const rankDiff = (left.rank ?? 999999) - (right.rank ?? 999999);
      if (rankDiff !== 0) return rankDiff;
      const weightDiff = (right.weight ?? -Infinity) - (left.weight ?? -Infinity);
      if (Number.isFinite(weightDiff) && weightDiff !== 0) return weightDiff;
      return left.normalizedKeyword.localeCompare(right.normalizedKeyword);
    });
}

function ignoredTermSet(
  rules: LexicalSteeringRuleRecord[],
  context: { categorySetId: string; corpusId: string; classifierId?: string | null; categoryKey: string },
  archived: boolean,
): Set<string> {
  return new Set(
    rules
      .filter((rule) => rule.ruleKind === "ignored_keyword")
      .filter((rule) => archived ? rule.status !== "active" : rule.status === "active")
      .filter((rule) => lexicalRuleApplies(rule, context))
      .map((rule) => rule.normalizedTerm),
  );
}

function lexicalRuleApplies(
  rule: LexicalSteeringRuleRecord,
  context: { categorySetId: string; corpusId: string; classifierId?: string | null; categoryKey: string },
): boolean {
  if (rule.scope === "publication") return true;
  if (rule.scope === "corpus") return !rule.corpusId || rule.corpusId === context.corpusId;
  if (rule.scope === "classifier") {
    return (!rule.corpusId || rule.corpusId === context.corpusId)
      && (!rule.classifierId || rule.classifierId === context.classifierId);
  }
  if (rule.scope === "category") {
    return (!rule.categorySetId || rule.categorySetId === context.categorySetId)
      && (!rule.categoryKey || rule.categoryKey === context.categoryKey);
  }
  return false;
}

function normalizeKeywordTerm(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}\s-]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function upsertLocalLexicalRule(rules: LexicalSteeringRuleRecord[], rule: LexicalSteeringRuleRecord): LexicalSteeringRuleRecord[] {
  const withoutExisting = rules.filter((entry) => entry.id !== rule.id);
  return [rule, ...withoutExisting].sort((left, right) => `${left.scope}#${left.normalizedTerm}`.localeCompare(`${right.scope}#${right.normalizedTerm}`));
}

function hashUiKey(values: unknown[]): string {
  const text = values.map((value) => String(value ?? "")).join("|");
  let hash = 5381;
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) + hash) ^ text.charCodeAt(index);
  }
  return Math.abs(hash >>> 0).toString(16);
}

function uniqueSemanticSummaries(objects: SemanticObjectSummary[]): SemanticObjectSummary[] {
  const map = new Map<string, SemanticObjectSummary>();
  for (const object of objects) map.set(`${object.kind}#${object.lineageId}`, object);
  return Array.from(map.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function normalizeReferenceSubscriptionPayload(value: unknown): ReferenceRecord | null {
  if (!value || typeof value !== "object") return null;
  const record = value as { data?: unknown; id?: unknown };
  if (typeof record.id === "string") return record as ReferenceRecord;
  if (record.data && typeof record.data === "object" && typeof (record.data as { id?: unknown }).id === "string") {
    return record.data as ReferenceRecord;
  }
  return null;
}

function normalizeSemanticRelationSubscriptionPayload(value: unknown): SemanticRelationRecord | null {
  if (!value || typeof value !== "object") return null;
  const record = value as { data?: unknown; id?: unknown };
  if (typeof record.id === "string") return record as SemanticRelationRecord;
  if (record.data && typeof record.data === "object" && typeof (record.data as { id?: unknown }).id === "string") {
    return record.data as SemanticRelationRecord;
  }
  return null;
}

function normalizeModelAttachmentSubscriptionPayload(value: unknown): ModelAttachmentRecord | null {
  if (!value || typeof value !== "object") return null;
  const record = value as { data?: unknown; id?: unknown };
  if (
    typeof (record as { ownerId?: unknown }).ownerId === "string"
    && typeof (record as { ownerKind?: unknown }).ownerKind === "string"
    && typeof (record as { role?: unknown }).role === "string"
  ) {
    return record as ModelAttachmentRecord;
  }
  if (record.data && typeof record.data === "object") {
    const payload = record.data as { ownerId?: unknown; ownerKind?: unknown; role?: unknown };
    if (typeof payload.ownerId === "string" && typeof payload.ownerKind === "string" && typeof payload.role === "string") {
      return record.data as ModelAttachmentRecord;
    }
  }
  return null;
}

function extractSubscriptionRecordId(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as { id?: unknown; data?: unknown };
  if (typeof record.id === "string") return record.id;
  if (record.data && typeof record.data === "object" && typeof (record.data as { id?: unknown }).id === "string") {
    return (record.data as { id: string }).id;
  }
  return null;
}

function buildReviewedReferenceRecord(
  records: ReferenceRecord[],
  reference: ReferenceRecord,
  options: {
    actorLabel: string;
    nextStatus: string;
    note: string | null;
    now: string;
  },
): ReferenceRecord {
  const current = records.find((entry) => entry.id === reference.id) ?? reference;
  return {
    ...current,
    curationStatus: options.nextStatus,
    curationStatusKey: `${current.corpusId}#${options.nextStatus}`,
    curationStatusUpdatedAt: options.now,
    curationStatusUpdatedBy: options.actorLabel,
    curationStatusReason: options.note,
    updatedAt: options.now,
  };
}

function upsertReferenceRecords(
  current: ReferenceRecord[],
  nextReference: ReferenceRecord,
): { nextRecords: ReferenceRecord[]; nextRecord: ReferenceRecord; previousRecord: ReferenceRecord | null } {
  const lineageId = referenceLineageId(nextReference);
  const previousRecord = selectedReferenceRecordByLineage(current, lineageId);
  const merged = [
    nextReference,
    ...current.filter((entry) => entry.id !== nextReference.id),
  ];
  const nextRecords = sortReferencesByRecency(selectCanonicalReferenceRecords(merged));
  const nextRecord = selectedReferenceRecordByLineage(nextRecords, lineageId) ?? nextReference;
  return {
    nextRecords,
    nextRecord,
    previousRecord,
  };
}

function patchReferenceSummary(
  summary: NewsroomSummaryRecord | null | undefined,
  previousReference: ReferenceRecord | null,
  nextReference: ReferenceRecord,
): NewsroomSummaryRecord | null {
  if (!summary) return null;
  const totalDelta = previousReference ? 0 : 1;
  const previousStatus = previousReference ? normalizeReferenceStatus(previousReference.curationStatus) : null;
  const nextStatus = normalizeReferenceStatus(nextReference.curationStatus);
  const previousCorpusId = previousReference?.corpusId ?? null;
  const nextCorpusId = nextReference.corpusId;

  const counts = applyCountDelta(summary.counts, "references", totalDelta);
  const referenceStatusCounts = { ...summary.referenceStatusCounts };
  const facets = summary.facets ? { ...summary.facets } : undefined;
  const referenceFacets = summary.facets?.references
    ? {
        ...summary.facets.references,
        byCurationStatus: { ...(summary.facets.references.byCurationStatus ?? {}) },
        byCorpus: { ...(summary.facets.references.byCorpus ?? {}) },
        statusByCorpus: cloneNestedNumberCounts(summary.facets.references.statusByCorpus),
      }
    : undefined;

  if (previousStatus !== nextStatus) {
    if (previousStatus) decrementCount(referenceStatusCounts, previousStatus);
    incrementCount(referenceStatusCounts, nextStatus);
    if (referenceFacets?.byCurationStatus) {
      if (previousStatus) decrementCount(referenceFacets.byCurationStatus, previousStatus);
      incrementCount(referenceFacets.byCurationStatus, nextStatus);
    }
  } else if (!previousReference) {
    incrementCount(referenceStatusCounts, nextStatus);
    if (referenceFacets?.byCurationStatus) incrementCount(referenceFacets.byCurationStatus, nextStatus);
  }

  if (!previousReference) {
    if (referenceFacets?.byCorpus) incrementCount(referenceFacets.byCorpus, nextCorpusId);
    if (referenceFacets?.statusByCorpus) {
      const corpusCounts = { ...(referenceFacets.statusByCorpus[nextCorpusId] ?? {}) };
      incrementCount(corpusCounts, nextStatus);
      referenceFacets.statusByCorpus[nextCorpusId] = corpusCounts;
    }
  } else if (referenceFacets?.statusByCorpus) {
    const previousKey = previousCorpusId ?? nextCorpusId;
    const previousCorpusCounts = { ...(referenceFacets.statusByCorpus[previousKey] ?? {}) };
    if (previousKey !== nextCorpusId) {
      decrementCount(previousCorpusCounts, previousStatus ?? nextStatus);
      referenceFacets.statusByCorpus[previousKey] = previousCorpusCounts;
      if (referenceFacets.byCorpus) decrementCount(referenceFacets.byCorpus, previousKey);
      if (referenceFacets.byCorpus) incrementCount(referenceFacets.byCorpus, nextCorpusId);
      const nextCorpusCounts = { ...(referenceFacets.statusByCorpus[nextCorpusId] ?? {}) };
      incrementCount(nextCorpusCounts, nextStatus);
      referenceFacets.statusByCorpus[nextCorpusId] = nextCorpusCounts;
    } else if (previousStatus !== nextStatus) {
      decrementCount(previousCorpusCounts, previousStatus ?? nextStatus);
      incrementCount(previousCorpusCounts, nextStatus);
      referenceFacets.statusByCorpus[nextCorpusId] = previousCorpusCounts;
    }
  }

  if (facets && referenceFacets) facets.references = referenceFacets;
  return {
    ...summary,
    counts,
    referenceStatusCounts,
    facets: facets ?? summary.facets,
  };
}

function patchReferenceSummaryForDelete(
  summary: NewsroomSummaryRecord | null | undefined,
  deletedReference: ReferenceRecord | null,
): NewsroomSummaryRecord | null {
  if (!summary || !deletedReference) return summary ?? null;
  const deletedStatus = normalizeReferenceStatus(deletedReference.curationStatus);
  const deletedCorpusId = deletedReference.corpusId;
  const counts = applyCountDelta(summary.counts, "references", -1);
  const referenceStatusCounts = { ...summary.referenceStatusCounts };
  decrementCount(referenceStatusCounts, deletedStatus);
  const facets = summary.facets ? { ...summary.facets } : undefined;
  const referenceFacets = summary.facets?.references
    ? {
        ...summary.facets.references,
        byCurationStatus: { ...(summary.facets.references.byCurationStatus ?? {}) },
        byCorpus: { ...(summary.facets.references.byCorpus ?? {}) },
        statusByCorpus: cloneNestedNumberCounts(summary.facets.references.statusByCorpus),
      }
    : undefined;
  if (referenceFacets?.byCurationStatus) decrementCount(referenceFacets.byCurationStatus, deletedStatus);
  if (referenceFacets?.byCorpus) decrementCount(referenceFacets.byCorpus, deletedCorpusId);
  if (referenceFacets?.statusByCorpus) {
    const corpusCounts = { ...(referenceFacets.statusByCorpus[deletedCorpusId] ?? {}) };
    decrementCount(corpusCounts, deletedStatus);
    referenceFacets.statusByCorpus[deletedCorpusId] = corpusCounts;
  }
  if (facets && referenceFacets) facets.references = referenceFacets;
  return {
    ...summary,
    counts,
    referenceStatusCounts,
    facets: facets ?? summary.facets,
  };
}

function upsertSemanticRelationRecords(
  current: SemanticRelationRecord[],
  relation: SemanticRelationRecord,
): SemanticRelationRecord[] {
  return [relation, ...current.filter((entry) => entry.id !== relation.id)];
}

function formatReferencesRealtimeStatusMessage(
  status: RealtimeSubscriptionStatus | undefined,
  error: string | null | undefined,
): string | null {
  if (!status || status === "idle" || status === "connected") return null;
  if (status === "connecting" || status === "reconnecting") return "References realtime is reconnecting.";
  if (status === "stale") return "References realtime is temporarily stale while reconnecting.";
  return error ? `References realtime is unavailable: ${error}` : "References realtime is unavailable.";
}

function cloneNestedNumberCounts(value: Record<string, Record<string, number>> | null | undefined): Record<string, Record<string, number>> {
  const result: Record<string, Record<string, number>> = {};
  for (const [key, counts] of Object.entries(value ?? {})) {
    result[key] = { ...counts };
  }
  return result;
}

function applyCountDelta(counts: Record<string, number>, key: string, delta: number): Record<string, number> {
  if (!delta) return counts;
  const nextCounts = { ...counts };
  const nextValue = (nextCounts[key] ?? 0) + delta;
  nextCounts[key] = nextValue < 0 ? 0 : nextValue;
  return nextCounts;
}

function incrementCount(counts: Record<string, number>, key: string): void {
  counts[key] = (counts[key] ?? 0) + 1;
}

function decrementCount(counts: Record<string, number>, key: string): void {
  const nextValue = (counts[key] ?? 0) - 1;
  counts[key] = nextValue < 0 ? 0 : nextValue;
}

function normalizeReferenceStatus(status: string | null | undefined): string {
  return status?.trim() || "pending";
}

function sortReferencesByRecency(references: ReferenceRecord[]): ReferenceRecord[] {
  return [...references].sort(compareReferencesByRecency);
}

function sortReferenceSummariesByRecency(references: SemanticObjectSummary[]): SemanticObjectSummary[] {
  return [...references].sort((left, right) => {
    const dateDiff = referenceSummarySortDate(right).localeCompare(referenceSummarySortDate(left));
    if (dateDiff !== 0) return dateDiff;
    return left.label.localeCompare(right.label);
  });
}

function compareReferencesByRecency(left: ReferenceRecord, right: ReferenceRecord): number {
  const dateDiff = referenceSortDate(right).localeCompare(referenceSortDate(left));
  if (dateDiff !== 0) return dateDiff;
  return (left.title ?? left.externalItemId).localeCompare(right.title ?? right.externalItemId);
}

function selectedReferenceRecordByLineage(
  references: ReferenceRecord[],
  requestedLineageId: string | null | undefined,
): ReferenceRecord | null {
  if (!requestedLineageId) return null;
  const lineageMatches = references.filter((reference) => referenceLineageId(reference) === requestedLineageId);
  if (!lineageMatches.length) return null;
  return lineageMatches.reduce((best, current) => (
    compareReferencesForCanonicalChoice(current, best) < 0 ? current : best
  ));
}

function selectCanonicalReferenceRecords(references: ReferenceRecord[]): ReferenceRecord[] {
  const byLineage = new Map<string, ReferenceRecord>();
  for (const reference of references) {
    const key = referenceLineageId(reference);
    const current = byLineage.get(key);
    if (!current || compareReferencesForCanonicalChoice(reference, current) < 0) {
      byLineage.set(key, reference);
    }
  }
  return Array.from(byLineage.values());
}

function referenceLineageId(reference: ReferenceRecord): string {
  return reference.lineageId ?? reference.id;
}

function compareReferencesForCanonicalChoice(left: ReferenceRecord, right: ReferenceRecord): number {
  const leftCurrent = left.versionState === "current" ? 1 : 0;
  const rightCurrent = right.versionState === "current" ? 1 : 0;
  if (leftCurrent !== rightCurrent) return rightCurrent - leftCurrent;

  const leftVersion = Number.isFinite(left.versionNumber) ? Number(left.versionNumber) : 0;
  const rightVersion = Number.isFinite(right.versionNumber) ? Number(right.versionNumber) : 0;
  if (leftVersion !== rightVersion) return rightVersion - leftVersion;

  return compareReferencesByRecency(left, right);
}

function referenceSortDate(reference: ReferenceRecord): string {
  return reference.sourcePublishedAt
    ?? reference.sourceUpdatedAt
    ?? reference.retrievedAt
    ?? reference.importedAt
    ?? reference.updatedAt
    ?? "";
}

function referencePublishedDate(reference: ReferenceRecord): string {
  return reference.sourcePublishedAt
    ?? reference.sourceUpdatedAt
    ?? "";
}

function referenceImportedDate(reference: ReferenceRecord): string {
  return reference.importedAt
    ?? reference.retrievedAt
    ?? reference.updatedAt
    ?? "";
}

function referenceSummarySortDate(reference: SemanticObjectSummary): string {
  return reference.kind === "reference" && reference.record
    ? referenceSortDate(reference.record as ReferenceRecord)
    : "";
}

function formatReferenceDate(reference: ReferenceRecord): string {
  const value = referenceSortDate(reference);
  return value ? formatShortDate(value) : "undated";
}

function formatReferencePublishedDate(reference: ReferenceRecord): string {
  const value = referencePublishedDate(reference);
  return value ? formatShortDate(value) : "undated";
}

function formatReferenceImportedDate(reference: ReferenceRecord): string {
  const value = referenceImportedDate(reference);
  return value ? formatShortDate(value) : "undated";
}

function formatReferenceSummaryDate(reference: SemanticObjectSummary): string {
  const value = referenceSummarySortDate(reference);
  return value ? formatShortDate(value) : "undated";
}

function formatShortDate(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(timestamp));
}

function referenceMatchesQuery(reference: ReferenceRecord, normalizedQuery: string): boolean {
  const authors = compactArray(reference.authors).join(" ");
  return [
    reference.title,
    reference.externalItemId,
    reference.sourceUri,
    reference.storagePath,
    reference.mediaType,
    authors,
  ]
    .filter((value): value is string => typeof value === "string" && value.length > 0)
    .some((value) => value.toLowerCase().includes(normalizedQuery));
}

function selectInitialRootKey(roots: CanonicalTopicRoot[], initialCategoryLineageId?: string | null): string | null {
  if (!roots.length) return null;
  if (!initialCategoryLineageId) return roots[0].category.categoryKey;
  for (const root of roots) {
    if (matchesCategorySelection(root.category, initialCategoryLineageId) || (root.node && matchesCategorySelection(root.node, initialCategoryLineageId))) {
      return root.category.categoryKey;
    }
    if (root.subcategorys.some((subcategory) => matchesCategorySelection(subcategory, initialCategoryLineageId))) {
      return root.category.categoryKey;
    }
  }
  return roots[0].category.categoryKey;
}

function selectInitialFocusKey(root: CanonicalTopicRoot | null, initialCategoryLineageId?: string | null): string | null {
  if (!root) return null;
  if (!initialCategoryLineageId) return root.category.categoryKey;
  if (matchesCategorySelection(root.category, initialCategoryLineageId) || (root.node && matchesCategorySelection(root.node, initialCategoryLineageId))) {
    return root.category.categoryKey;
  }
  const subcategory = root.subcategorys.find((candidate) => matchesCategorySelection(candidate, initialCategoryLineageId));
  return subcategory?.categoryKey ?? root.category.categoryKey;
}

function matchesCategorySelection(category: CategorySteeringCategory | CategorySteeringCategoryTreeNode, selection: string): boolean {
  return category.id === selection || category.lineageId === selection || category.categoryKey === selection;
}

function buildCategoryCopyVersion(
  category: CategorySteeringCategory,
  update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">,
  { actorLabel, now }: { actorLabel: string; now: string },
): CategorySteeringCategory {
  const lineageId = category.lineageId ?? category.id;
  const versionNumber = nextVersionNumber(category.versionNumber);
  const nextCategory: CategorySteeringCategory = {
    ...category,
    ...update,
    id: `${lineageId}-v${versionNumber}`,
    lineageId,
    versionNumber,
    previousVersionId: category.id,
    versionState: "current",
    versionCreatedAt: now,
    versionCreatedBy: actorLabel,
    changeReason: "manual category copy edit",
    updatedAt: now,
  };
  nextCategory.contentHash = contentHashFor(nextCategory);
  return nextCategory;
}

function nextVersionNumber(versionNumber: number | null | undefined): number {
  return typeof versionNumber === "number" && Number.isFinite(versionNumber)
    ? Math.max(1, Math.trunc(versionNumber)) + 1
    : 2;
}

function contentHashFor(value: unknown): string {
  return `fnv1a32:${stableHash(stripHash(value))}`;
}

function stripHash(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const copy: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (key === "contentHash") continue;
    copy[key] = entry;
  }
  return copy;
}

function stableHash(value: unknown): string {
  const text = stableStringify(value);
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, entry]) => entry !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return `{${entries.map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`).join(",")}}`;
}

function deskDoctrineStatus(category: DoctrineCategory, records: DoctrineRecord[]): { savedCount: number } {
  const savedCount = (["mission", "policy"] as DoctrineKind[]).filter((kind) => {
    const definition = buildCategoryDoctrineDefinition(category, kind);
    const record = records.find((entry) => entry.slug === definition.slug);
    return doctrineTextToBody(doctrineBodyToText(record?.body)).length > 0;
  }).length;
  return { savedCount };
}

function countAssignmentsForDesk(
  assignments: AssignmentRecord[],
  graph: SemanticGraph,
  rootNode: CategorySteeringCategoryTreeNode,
  subcategorys: CategorySteeringCategoryTreeNode[],
): number {
  const categoryKeys = new Set([rootNode.categoryKey, ...subcategorys.map((subcategory) => subcategory.categoryKey)]);
  const categoryLineages = new Set([rootNode, ...subcategorys].map((category) => categoryLineageId(category)));
  return assignments.filter((assignment) => {
    const metadataCategoryKey = assignmentMetadataCategoryKey(assignment);
    if (metadataCategoryKey && categoryKeys.has(metadataCategoryKey)) return true;
    return graph.outgoing("assignment", assignment.id).some((relation) => (
      relation.objectKind === "category"
      && categoryLineages.has(relation.objectLineageId)
    ));
  }).length;
}

function assignmentMetadataCategoryKey(assignment: AssignmentRecord): string | null {
  const metadata = parseMetadataObject(assignment.metadata);
  return normalizeMetadataString(assignment.primaryFocusCategoryKey)
    ?? normalizeMetadataStringList(assignment.topicScopeCategoryKeys)[0]
    ?? normalizeMetadataString(metadata?.focusCategoryKey)
    ?? normalizeMetadataString(metadata?.deskCategoryKey)
    ?? normalizeMetadataString(metadata?.categoryKey)
    ?? normalizeMetadataString(metadata?.category_key)
    ?? normalizeMetadataString(metadata?.rootCategoryKey)
    ?? normalizeMetadataString(metadata?.root_category_key)
    ?? normalizeMetadataString(metadata?.topicUid)
    ?? normalizeMetadataString(metadata?.topic_uid)
    ?? nestedMetadataCategoryKey(metadata?.newsroom)
    ?? nestedMetadataCategoryKey(metadata?.assignment);
}

function nestedMetadataCategoryKey(value: unknown): string | null {
  const metadata = parseMetadataObject(value);
  return normalizeMetadataString(metadata?.focusCategoryKey)
    ?? normalizeMetadataString(metadata?.deskCategoryKey)
    ?? normalizeMetadataString(metadata?.categoryKey)
    ?? normalizeMetadataString(metadata?.category_key)
    ?? normalizeMetadataString(metadata?.rootCategoryKey)
    ?? normalizeMetadataString(metadata?.root_category_key)
    ?? normalizeMetadataString(metadata?.topicUid)
    ?? normalizeMetadataString(metadata?.topic_uid);
}

function parseMetadataObject(value: unknown): Record<string, unknown> | null {
  if (!value) return null;
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function normalizeMetadataString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeMetadataStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => normalizeMetadataString(entry))
    .filter((entry): entry is string => Boolean(entry));
}

function assignmentContextMetadata(assignment: AssignmentRecord): {
  deskKey: string | null;
  deskTitle: string | null;
  focusKey: string | null;
  focusTitle: string | null;
  contextProfile: string | null;
  contextTokenBudget: number | null;
  contextSources: string[];
  targetSystemType: string | null;
  expectedEvidenceClasses: string[];
  comparisonQuestions: string[];
} | null {
  const metadata = parseMetadataObject(assignment.metadata);
  const deskKey = normalizeMetadataString(assignment.sectionKey)
    ?? normalizeMetadataString(assignment.sectionId)
    ?? normalizeMetadataString(metadata?.deskCategoryKey)
    ?? normalizeMetadataString(metadata?.rootCategoryKey);
  const focusKey = normalizeMetadataString(assignment.primaryFocusCategoryKey)
    ?? normalizeMetadataStringList(assignment.topicScopeCategoryKeys)[0]
    ?? normalizeMetadataString(metadata?.focusCategoryKey)
    ?? normalizeMetadataString(metadata?.researchLens);
  if (!deskKey && !focusKey) return null;
  const contextTokenBudgetValue = typeof metadata?.contextTokenBudget === "number"
    ? metadata.contextTokenBudget
    : typeof metadata?.contextTokenBudget === "string" && metadata.contextTokenBudget.trim()
      ? Number(metadata.contextTokenBudget)
      : null;
  return {
    deskKey,
    deskTitle: normalizeMetadataString(metadata?.deskCategoryTitle)
      ?? normalizeMetadataString(metadata?.rootCategoryTitle)
      ?? deskKey,
    focusKey,
    focusTitle: normalizeMetadataString(metadata?.focusCategoryTitle)
      ?? normalizeMetadataString(metadata?.researchLensTitle)
      ?? focusKey,
    contextProfile: normalizeMetadataString(metadata?.contextProfile),
    contextTokenBudget: Number.isFinite(contextTokenBudgetValue) ? Number(contextTokenBudgetValue) : null,
    contextSources: normalizeMetadataStringList(metadata?.contextSources),
    targetSystemType: normalizeMetadataString(metadata?.targetSystemType),
    expectedEvidenceClasses: normalizeMetadataStringList(metadata?.expectedEvidenceClasses),
    comparisonQuestions: normalizeMetadataStringList(metadata?.comparisonQuestions),
  };
}

type AssignmentAnalysisReindexSummary = {
  profileTitle: string;
  mode: string;
  corpusKey: string;
  commandLines: string[];
  destructiveSummary: string;
};

function assignmentAnalysisReindexMetadata(assignment: AssignmentRecord): AssignmentAnalysisReindexSummary | null {
  const metadata = parseMetadataObject(assignment.metadata);
  if (!metadata && assignment.assignmentTypeKey !== "analysis.reindex") return null;
  if (metadata && metadata.kind !== "analysis.reindex.requested" && assignment.assignmentTypeKey !== "analysis.reindex") return null;
  const commandPlan = normalizeMetadataObjectList(metadata?.commandPlan);
  const commandLines = commandPlan.map((command) => {
    const executable = normalizeMetadataString(command.executable) ?? "uv";
    const args = Array.isArray(command.args) ? command.args.map((arg) => String(arg)) : [];
    return [executable, ...args].join(" ");
  }).filter(Boolean);
  const destructivePlan = parseMetadataObject(metadata?.destructivePlan);
  return {
    profileTitle: normalizeMetadataString(metadata?.analysisProfileTitle)
      ?? normalizeMetadataString(metadata?.analysisProfileKey)
      ?? normalizeMetadataString(assignment.title)
      ?? "analysis profile",
    mode: normalizeMetadataString(metadata?.reindexMode) ?? "re-index",
    corpusKey: normalizeMetadataString(metadata?.corpusKey) ?? assignment.corpusId ?? "corpus",
    commandLines,
    destructiveSummary: normalizeMetadataString(destructivePlan?.summary) ?? "Assignment creation does not execute Biblicus or mutate generated analysis.",
  };
}

type AssignmentResearchPacketSummary = {
  id: string;
  kind: string;
  label: string;
  summary: string;
  createdAt: string;
  queryCount: number;
  proposedReferenceCount: number;
  sourceDomains: string[];
};
type ReportingPacketDecisionSummary = {
  decision: ReportingPacketReviewDecision;
  copywritingAssignmentId?: string | null;
  copywritingStatus?: string | null;
  draftItemId?: string | null;
  eventId: string;
  note?: string | null;
  targetItemId?: string | null;
};
type UiReportingReviewItemTarget = {
  id: string;
  lineageId?: string | null;
  versionNumber?: number | null;
};

function reportingPacketsForAssignment(
  assignment: AssignmentRecord,
  graph: SemanticGraph,
  messages: MessageRecord[],
): AssignmentResearchPacketSummary[] {
  return researchPacketsForAssignment(assignment, graph, messages).filter((packet) => packet.kind === "reporting_context_packet");
}

function researchPacketsForAssignment(
  assignment: AssignmentRecord,
  graph: SemanticGraph,
  messages: MessageRecord[],
): AssignmentResearchPacketSummary[] {
  const linked = graph.messagesFor("assignment", assignment.id);
  const candidates = linked.length ? linked : messages;
  return candidates
    .filter((message) => message.messageKind === "research_packet" || message.messageKind === "reporting_context_packet")
    .map((message) => {
      return {
        id: message.id,
        kind: message.messageKind,
        label: message.messageKind === "reporting_context_packet" ? "Reporting packet" : "Research packet",
        summary: message.summary ?? "Stored research packet",
        createdAt: message.createdAt,
        queryCount: 0,
        proposedReferenceCount: 0,
        sourceDomains: [] as string[],
      };
    })
    .filter((packet): packet is AssignmentResearchPacketSummary => Boolean(packet))
    .sort((left, right) => right.createdAt.localeCompare(left.createdAt));
}

function normalizeMetadataObjectList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is Record<string, unknown> => Boolean(parseMetadataObject(entry)));
}

function countRelatedCategoryTreeProposals(
  categoryKey: string,
  subcategorys: CategorySteeringCategoryTreeNode[],
  proposals: CategorySteeringProposal[],
): number {
  const categoryKeys = new Set([categoryKey, ...subcategorys.map((subcategory) => subcategory.categoryKey)]);
  return proposals.filter((proposal) => {
    if (!TAXONOMY_PROPOSAL_KINDS.has(proposal.proposalKind)) return false;
    return Boolean(
      (proposal.categoryKey && categoryKeys.has(proposal.categoryKey)) ||
      (proposal.targetCategoryKey && categoryKeys.has(proposal.targetCategoryKey)),
    );
  }).length;
}

function getProposedSubcategoryProposals(rootCategoryUid: string, proposals: CategorySteeringProposal[]): CategorySteeringProposal[] {
  return proposals
    .filter((proposal) => (
      proposal.proposalKind === "create-category"
      && proposal.status === "proposed"
      && proposal.targetCategoryKey === rootCategoryUid
    ))
    .sort((left, right) => {
      const leftName = left.displayName ?? left.title;
      const rightName = right.displayName ?? right.title;
      return leftName.localeCompare(rightName);
    });
}

function CorpusCategorySetSummary({
  corpora,
  categorySets,
  importRuns,
  canonicalCategorySetId,
}: {
  corpora: CategorySteeringCorpus[];
  categorySets: CategorySteeringCategorySet[];
  importRuns: CategorySteeringImportRun[];
  canonicalCategorySetId: string | null;
}) {
  return (
    <section className="category-steering-section" aria-labelledby="corpus-category-sets-title">
      <SectionHeader title="Corpus Category Sets" detail={`${corpora.length} configured corpora / ${categorySets.length} registers`} />
      <div className="news-desk-ledger-list">
        {corpora.length ? corpora.map((corpus) => {
          const corpusCategorySets = categorySets.filter((categorySet) => categorySet.corpusId === corpus.id);
          const latestImport = importRuns.find((importRun) => importRun.corpusId === corpus.id);
          return (
            <article className="news-desk-ledger-item" key={corpus.id}>
              <header>
                <strong>{corpus.name}</strong>
                <span>{corpus.role}</span>
              </header>
              <dl>
                <div>
                  <dt>Category Sets</dt>
                  <dd>{formatCategorySetNames(corpusCategorySets, canonicalCategorySetId)}</dd>
                </div>
                <div>
                  <dt>Classifiers</dt>
                  <dd>{corpusCategorySets.map((categorySet) => categorySet.classifierId).join(" / ") || "none"}</dd>
                </div>
                <div>
                  <dt>Categories</dt>
                  <dd>{String(corpusCategorySets.reduce((count, categorySet) => count + (categorySet.categoryCount ?? 0), 0))}</dd>
                </div>
                <div>
                  <dt>Latest Import</dt>
                  <dd>{latestImport ? formatDateTime(latestImport.importedAt) : "none"}</dd>
                </div>
              </dl>
            </article>
          );
        }) : <EmptyRow label="No steering corpora imported" />}
      </div>
    </section>
  );
}

function formatCategorySetNames(categorySets: CategorySteeringCategorySet[], canonicalCategorySetId: string | null): string {
  if (!categorySets.length) return "No category sets";
  return categorySets
    .map((categorySet) => `${categorySet.displayName}${categorySet.id === canonicalCategorySetId ? " (canonical)" : ""}`)
    .join(" / ");
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(timestamp));
}

function deriveShortTitle(value: string | null | undefined): string {
  const words = String(value ?? "")
    .replace(/[_/|]+/g, " ")
    .replace(/[^\p{L}\p{N}\s&+-]/gu, "")
    .split(/\s+/)
    .map((word) => word.trim())
    .filter(Boolean);
  return words.length ? words.slice(0, 3).join(" ") : "Topic";
}

function buildReferenceLookupByAnyId(references: ReferenceRecord[]): Map<string, ReferenceRecord> {
  const map = new Map<string, ReferenceRecord>();
  for (const reference of references) {
    const keys = [
      reference.id,
      reference.lineageId ?? undefined,
      reference.externalItemId,
    ].filter((value): value is string => Boolean(value));
    for (const key of keys) {
      map.set(key, reference);
    }
  }
  return map;
}

function proposalEvidenceIds(proposal: CategorySteeringProposal, limit = 20): string[] {
  return Array.from(new Set([
    ...compactArray(proposal.suggestedSeedItemIds),
    ...compactArray(proposal.evidenceItemIds),
  ])).slice(0, limit);
}

function proposalEvidenceCount(proposal: CategorySteeringProposal): number {
  const ids = compactArray(proposal.evidenceItemIds);
  if (ids.length) return ids.length;
  return proposalEvidenceIds(proposal, 20).length;
}

function evidenceExamplesForIds(
  evidenceIds: string[],
  referenceByAnyId: Map<string, ReferenceRecord>,
  limit = 20,
): ProposalEvidenceEntry[] {
  return evidenceIds.slice(0, limit).map((evidenceId) => {
    const reference = referenceByAnyId.get(evidenceId);
    if (!reference) {
      return { id: evidenceId, title: evidenceId, href: null };
    }
    const lineageId = reference.lineageId ?? reference.id;
    return {
      id: evidenceId,
      title: reference.title ?? reference.externalItemId ?? evidenceId,
      href: lineageId ? newsDeskHrefForSemanticObject("reference", lineageId) : null,
    };
  });
}

function proposalEvidenceExamples(
  proposal: CategorySteeringProposal,
  referenceByAnyId: Map<string, ReferenceRecord>,
  limit = 20,
): ProposalEvidenceEntry[] {
  return evidenceExamplesForIds(proposalEvidenceIds(proposal, limit), referenceByAnyId, limit);
}

function CategoryProposalRow({
  proposal,
  category,
  disabled,
  onAction,
  onEdit,
}: {
  proposal: CategorySteeringProposal;
  category?: CategorySteeringCategory;
  disabled: boolean;
  onAction: (proposal: CategorySteeringProposal, action: ReviewAction) => void;
  onEdit: (proposal: CategorySteeringProposal) => void;
}) {
  const evidence = compactArray(proposal.evidenceItemIds).slice(0, 3);
  const normalizedKind = normalizeProposalKind(proposal.proposalKind);
  const hierarchyLabel = proposal.targetCategoryKey
    ? `Subtopic under ${proposal.targetCategoryKey}`
    : "Top-level topic";

  return (
    <article className="category-steering-proposal" data-proposal-domain={proposal.steeringDomain}>
      <div className="category-steering-proposal__main">
        <div className="category-steering-proposal__title">
          <StatusPill status={proposal.status} />
          <strong>{proposal.title}</strong>
          <span>{proposal.proposalKind}</span>
        </div>
        <p>{proposal.summary ?? "No summary provided."}</p>
        <dl>
          <div>
            <dt>Proposal Type</dt>
            <dd>{normalizedKind}</dd>
          </div>
          <div>
            <dt>Hierarchy</dt>
            <dd>{hierarchyLabel}</dd>
          </div>
          <div>
            <dt>Category UID</dt>
            <dd>{proposal.categoryKey ?? category?.categoryKey ?? "new category"}</dd>
          </div>
          <div>
            <dt>Parent / Target UID</dt>
            <dd>{proposal.targetCategoryKey ?? "none"}</dd>
          </div>
          <div>
            <dt>Display</dt>
            <dd>{proposal.displayName ?? category?.displayName ?? "pending"}</dd>
          </div>
          <div>
            <dt>Short Title</dt>
            <dd>{proposal.shortTitle ?? category?.shortTitle ?? "auto"}</dd>
          </div>
          <div>
            <dt>Subtitle</dt>
            <dd>{proposal.subtitle ?? category?.subtitle ?? "none"}</dd>
          </div>
        </dl>
        <div className="category-steering-evidence-chips">
          {evidence.length ? evidence.map((itemId) => (
            <span key={itemId}>{itemId}</span>
          )) : <span>No evidence rows</span>}
        </div>
      </div>
      <ProposalReviewActions
        disabled={disabled}
        proposal={proposal}
        onAction={onAction}
        onEdit={onEdit}
      />
    </article>
  );
}

function normalizeProposalKind(proposalKind: string): "create" | "merge" | "delete" {
  const normalized = proposalKind.toLowerCase();
  if (normalized.includes("merge")) return "merge";
  if (normalized.includes("archive") || normalized.includes("deprecate") || normalized.includes("delete")) return "delete";
  return "create";
}

function CategoryEditor({
  category,
  disabled,
  onSave,
}: {
  category: CategorySteeringCategory;
  disabled: boolean;
  onSave: (category: CategorySteeringCategory, update: Pick<CategorySteeringCategory, "displayName" | "shortTitle" | "subtitle" | "description">) => void;
}) {
  const [displayName, setDisplayName] = useState(category.displayName);
  const [shortTitle, setShortTitle] = useState(category.shortTitle ?? deriveShortTitle(category.displayName));
  const [subtitle, setSubtitle] = useState(category.subtitle ?? "");
  const [description, setDescription] = useState(category.description ?? "");

  useEffect(() => {
    setDisplayName(category.displayName);
    setShortTitle(category.shortTitle ?? deriveShortTitle(category.displayName));
    setSubtitle(category.subtitle ?? "");
    setDescription(category.description ?? "");
  }, [category.description, category.displayName, category.id, category.shortTitle, category.subtitle]);

  return (
    <article className="category-steering-category-card" data-category-uid={category.categoryKey} data-saved-display-name={category.displayName}>
      <header>
        <span>{category.categoryKey}</span>
        <StatusPill status={category.status} />
      </header>
      <label>
        <span>Name</span>
        <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
      </label>
      <label>
        <span>Short Title</span>
        <input
          aria-describedby={`${category.id}-short-title-help`}
          value={shortTitle}
          onChange={(event) => setShortTitle(event.target.value)}
        />
        <small id={`${category.id}-short-title-help`}>Used for URL slugs and eyebrow headers; it does not need to be unique.</small>
      </label>
      <label>
        <span>Subtitle</span>
        <input value={subtitle} onChange={(event) => setSubtitle(event.target.value)} />
      </label>
      <label>
        <span>Description</span>
        <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} />
      </label>
      <footer>
        <span>{compactArray(category.seedItemIds).length} seeds / {compactArray(category.holdoutItemIds).length} holdouts</span>
        <button type="button" data-news-desk-command="save-copy" disabled={disabled || !displayName.trim() || !shortTitle.trim()} onClick={() => onSave(category, { displayName, shortTitle, subtitle, description })}>Save</button>
      </footer>
    </article>
  );
}

function CategorySetPanel({
  categorySet,
  artifacts,
  references,
  referenceAttachments,
  messages,
  semanticRelations,
}: {
  categorySet: CategorySteeringCategorySet | null;
  artifacts: CategorySteeringArtifact[];
  references: ReferenceRecord[];
  referenceAttachments: { id: string }[];
  messages: { id: string; messageKind: string }[];
  semanticRelations: SemanticRelationRecord[];
}) {
  return (
    <section className="category-steering-section" aria-labelledby="pressroom-export-title">
      <SectionHeader title="Pressroom Export" detail={categorySet?.status ?? "No category set"} />
      <div className="category-steering-revision-panel">
        <dl>
          <div>
            <dt>Current Version</dt>
            <dd>{categorySet?.versionNumber ?? "none"}</dd>
          </div>
          <div>
            <dt>Version State</dt>
            <dd>{categorySet?.versionState ?? "unknown"}</dd>
          </div>
          <div>
            <dt>Artifacts</dt>
            <dd>{artifacts.length}</dd>
          </div>
          <div>
            <dt>References</dt>
            <dd>{references.length}</dd>
          </div>
          <div>
            <dt>Attachments</dt>
            <dd>{referenceAttachments.length}</dd>
          </div>
          <div>
            <dt>Ingestion Rationales</dt>
            <dd>{messages.filter((message) => message.messageKind === "ingestion_rationale").length}</dd>
          </div>
          <div>
            <dt>Review Links</dt>
            <dd>{semanticRelations.filter((relation) => relation.reviewRecommended).length}</dd>
          </div>
        </dl>
        <div className="category-steering-artifacts">
          {artifacts.slice(0, 4).map((artifact) => {
            const label = artifact.displayName ?? artifact.artifactId;
            return (
              <span key={artifact.id} aria-label={label} title={label}>
                {formatArtifactChipLabel(label)}
              </span>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function StatusPill({ status }: { status: string }) {
  return <span className={`category-steering-pill category-steering-pill--${status}`}>{status}</span>;
}

function EmptyRow({ label }: { label: string }) {
  return <div className="category-steering-empty">{label}</div>;
}

function buildDoctrineEditorState(records: DoctrineRecord[]): DoctrineEditorState {
  return {
    mission: doctrineBodyToText(findDoctrineRecord(records, "mission")?.body),
    policy: doctrineBodyToText(findDoctrineRecord(records, "policy")?.body),
  };
}

function findDoctrineRecord(records: DoctrineRecord[], kind: DoctrineKind): DoctrineRecord | null {
  const definition = requireDoctrineDefinition(kind);
  return records.find((record) => record.slug === definition.slug) ?? null;
}

function requireDoctrineDefinition(kind: DoctrineKind) {
  const definition = DOCTRINE_DEFINITION_BY_KIND.get(kind);
  if (!definition) throw new Error(`Unknown doctrine kind ${kind}`);
  return definition;
}

function buildDoctrineRecord(
  kind: DoctrineKind,
  body: string[],
  currentRecord: DoctrineRecord | null,
  now: string,
  actorLabel: string,
): DoctrineRecord {
  const definition = requireDoctrineDefinition(kind);
  return {
    id: currentRecord?.id ?? definition.id,
    lineageId: currentRecord?.lineageId ?? definition.lineageId,
    versionNumber: currentRecord?.versionNumber ?? 1,
    versionState: currentRecord?.versionState ?? "current",
    versionCreatedAt: currentRecord?.versionCreatedAt ?? now,
    versionCreatedBy: currentRecord?.versionCreatedBy ?? actorLabel,
    type: DOCTRINE_ITEM_TYPE,
    status: currentRecord?.status ?? DOCTRINE_ITEM_STATUS,
    typeStatus: currentRecord?.typeStatus ?? DOCTRINE_ITEM_TYPE_STATUS,
    slug: definition.slug,
    title: definition.label,
    headline: definition.label,
    body,
    editorial: doctrineEditorialValue(kind),
    updatedAt: now,
  };
}

function buildCategoryDoctrineRecord(
  category: DoctrineCategory,
  kind: DoctrineKind,
  body: string[],
  currentRecord: DoctrineRecord | null,
  now: string,
  actorLabel: string,
): DoctrineRecord {
  const definition = buildCategoryDoctrineDefinition(category, kind);
  const title = `${category.displayName} ${definition.label}`;
  return {
    id: currentRecord?.id ?? definition.id,
    lineageId: currentRecord?.lineageId ?? definition.lineageId,
    versionNumber: currentRecord?.versionNumber ?? 1,
    versionState: currentRecord?.versionState ?? "current",
    versionCreatedAt: currentRecord?.versionCreatedAt ?? now,
    versionCreatedBy: currentRecord?.versionCreatedBy ?? actorLabel,
    type: DOCTRINE_ITEM_TYPE,
    status: currentRecord?.status ?? DOCTRINE_ITEM_STATUS,
    typeStatus: currentRecord?.typeStatus ?? DOCTRINE_ITEM_TYPE_STATUS,
    slug: definition.slug,
    title,
    headline: title,
    body,
    editorial: categoryDoctrineEditorialValue(category, kind),
    updatedAt: now,
  };
}

function replaceDoctrineRecord(records: DoctrineRecord[], nextRecord: DoctrineRecord): DoctrineRecord[] {
  const next = records.filter((record) => record.slug !== nextRecord.slug);
  next.push(nextRecord);
  return next.sort((left, right) => left.slug.localeCompare(right.slug));
}

function compactArray(value: Array<string | null> | null | undefined): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => (typeof entry === "string" ? entry.trim() : "")).filter(Boolean);
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)))).sort();
}

function formatArtifactChipLabel(value: string | null | undefined): string {
  const label = value?.trim() ?? "";
  if (!label) return "Untitled artifact";
  if (label.length <= 44) return label;

  const kindHashMatch = label.match(/^([^:\s]+:)([a-f0-9]{24,})$/i);
  if (kindHashMatch) {
    const [, prefix, hash] = kindHashMatch;
    return `${prefix}${hash.slice(0, 8)}…${hash.slice(-8)}`;
  }

  return `${label.slice(0, 24)}…${label.slice(-12)}`;
}

function formatUserLabel(user: UserDirectoryEntry): string {
  return user.displayName ?? user.email ?? user.username ?? user.userSub ?? user.userProfileId ?? "Unknown user";
}

function getUserDirectoryEntryKey(user: UserDirectoryEntry): string {
  return user.userProfileId ?? user.userSub ?? user.email ?? user.username ?? formatUserLabel(user);
}

function mergeDemoUsers(users: UserDirectoryEntry[], source: UserDirectoryEntry, target: UserDirectoryEntry): UserDirectoryEntry[] {
  const sourceKey = getUserDirectoryEntryKey(source);
  const targetKey = getUserDirectoryEntryKey(target);
  const targetProfileId = target.userProfileId ?? `user-profile-demo-${targetKey.replace(/[^a-z0-9-]/gi, "-").toLowerCase()}`;
  return users.reduce<UserDirectoryEntry[]>((entries, entry) => {
    if (getUserDirectoryEntryKey(entry) === targetKey) {
      const mergedIdentity = source.identities.length
        ? source.identities.map((identity) => ({ ...identity, userProfileId: targetProfileId }))
        : source.userSub
          ? [{
              id: `user-identity-demo-merged-${source.userSub}`,
              userProfileId: targetProfileId,
              cognitoSub: source.userSub,
              provider: source.provider ?? "cognito",
              email: source.email ?? null,
              status: "active",
              linkedAt: new Date().toISOString(),
              lastSeenAt: new Date().toISOString(),
            }]
          : [];
      entries.push({
        ...entry,
        userProfileId: targetProfileId,
        activeRoles: Array.from(new Set([...compactArray(entry.activeRoles), ...compactArray(source.activeRoles)])).sort(),
        identities: uniqueIdentities([...entry.identities, ...mergedIdentity]),
      });
      return entries;
    }
    if (getUserDirectoryEntryKey(entry) === sourceKey) return entries;
    entries.push(entry);
    return entries;
  }, []);
}

function uniqueIdentities(identities: UserDirectoryEntry["identities"]): UserDirectoryEntry["identities"] {
  const seen = new Set<string>();
  const unique = [];
  for (const identity of identities) {
    const key = identity.cognitoSub || identity.id;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(identity);
  }
  return unique;
}

function isTailoredCategoryProposal(proposal: CategorySteeringProposal): boolean {
  return proposal.steeringDomain === "category" && TAILORED_TOPIC_PROPOSAL_KINDS.has(proposal.proposalKind);
}
