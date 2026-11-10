"use client";

import { ArrowLeftIcon, CheckIcon, CircleDashedIcon, ExternalLinkIcon, GlobeLockIcon, ImagePlusIcon, ImagesIcon, RouteIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { newsroomDeskPickerOptions } from "../lib/newsroom-sections";
import { useNewsroomDeskSections } from "./use-newsroom-desk-sections";
import { StoryReportingTrailView } from "./story-reporting-trail";
import { loadStoryReportingTrail } from "./story-reporting-trail-client";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { isGeneratedIdeaFrontMatter, stageForIdeaDecision, writeIdeaDecision, type IdeaDecisionRecord } from "../lib/idea-decision";
import { IdeaDecision } from "./idea-decision";
import { SeededFromReferenceNote } from "./seeded-from-reference-note";
import { CoverImagePicker, type PickedImage } from "./cover-image-picker";
import { accessTokenFromAmplify, createLiveStockImageClient } from "../lib/stock-images/client";
import { createDemoStockImageClient } from "../lib/stock-images/demo-client";
import { bodyWithCover, coverDirective, coverRecord, creditLine, frontMatterWithCover, replaceableCoverSources } from "../lib/stock-images/cover";
import { FRONT_MATTER_BLURB_KEY, FRONT_MATTER_SUBTITLE_KEY, FRONT_MATTER_TITLE_KEY, readFrontMatterText, writeFrontMatterText } from "../lib/front-matter-fields";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ContentActionFailure, type ContentActionError } from "../lib/content-actions-client";
import { newsroomHref } from "../lib/newsroom-base-path";
import {
  editorTypeChoices,
  typeLabel,
  emptyArticle,
  locateError,
  resolveArticlesBackend,
  stagingPreviewUrl,
  suggestSlug,
  type ArticlesBackend,
  type EditableArticle,
  type ErrorLocation,
  type NewsroomArticleEditorState,
} from "../lib/newsroom-articles";
import { resolveMediaBackend } from "../lib/newsroom-media-backend";
import {
  insertDirectiveAtSelection,
  readImageDimensions,
  uploadArticleImage,
} from "../lib/newsroom-media";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { getContentItemStageDefinitions, SITE_BRAND } from "../lib/site-brand";
import { isUntyped } from "../lib/content-item-lifecycle";
import { describeBase, siteStoryTypes, storyAddress } from "../lib/site-story-types";
import { cn } from "../lib/utils";
import { applyReplacement, inlineFindings, visibleFindings } from "../lib/editorial-checks";
import { graphqlEditorialBackend } from "../lib/editorial-checks-client";
import { demoEditorialBackend } from "../lib/editorial-checks-demo";
import type { FindingActions } from "./editorial-finding-card";
import { EditorialFindingsPanel } from "./editorial-findings-panel";
import { StarRating } from "./star-rating";
import { useStoryStars, type StoryStarsController } from "./use-story-stars";
import { EditorialPreviewPopover, type PreviewPopoverTarget } from "./editorial-preview-popover";
import { MarkusBodyEditor, type MarkusBodyEditorHandle } from "./markus-body-editor";
import { MarkusIrPreview } from "./markus-ir-preview";
import { useEditorialChecks } from "./use-editorial-checks";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { articlesAccessBlocked } from "./newsroom-articles-view";

const VALIDATION_DEBOUNCE_MS = 600;
const TEXTAREA_CLASS = "field-sizing-fixed font-mono text-sm md:text-sm";

type ValidationState =
  | { status: "checking" }
  | { status: "valid" }
  | { status: "invalid"; errors: ContentActionError[] }
  | { status: "unavailable"; message: string };

type Notice = { tone: "ok" | "error" | "info"; text: string };
type MobileTab = "edit" | "preview" | "trail" | "references";

function lineStartIndex(text: string, line: number): number {
  let index = 0;
  for (let current = 1; current < line; current += 1) {
    const next = text.indexOf("\n", index);
    if (next === -1) return text.length;
    index = next + 1;
  }
  return index;
}

function stateFromArticle(article: EditableArticle): NewsroomArticleEditorState {
  return {
    id: article.id,
    type: article.type,
    section: article.section ?? "",
    slug: article.slug,
    frontMatterYaml: article.frontMatterYaml,
    bodyMarkus: article.bodyMarkus,
    contentHash: article.contentHash,
    status: article.status,
    versionNumber: article.versionNumber,
    dirty: false,
  };
}

function failureMessage(error: unknown): string {
  if (error instanceof ContentActionFailure) return error.message;
  return error instanceof Error ? error.message : "The request failed.";
}

const NO_DESK_VALUE = "__no-desk__";

export function NewsroomArticleEditor({ articleId, demo, embedded = false, starsController }: {
  articleId: string;
  demo: boolean;
  embedded?: boolean;
  /** The rating store of the surface this editor sits in (the board's), so the card, the drawer and this editor show one rating. Without it the editor keeps its own. */
  starsController?: StoryStarsController;
}) {
  const session = useOptionalNewsDeskClient();
  const blocked = !(demo || isLocalPreviewEnabled()) && articlesAccessBlocked(session?.shell.phase);
  const previewMode = demo || isLocalPreviewEnabled();
  const backend: ArticlesBackend = useMemo(() => resolveArticlesBackend(previewMode), [previewMode]);
  const ownStars = useStoryStars((itemId, stars) => backend.actions.setItemStars(itemId, stars));
  const stars = starsController ?? ownStars;
  const [activeArticleId, setActiveArticleId] = useState(articleId);
  useEffect(() => { setActiveArticleId(articleId); }, [articleId]);
  const isNew = articleId === "new";

  const [editor, setEditor] = useState<NewsroomArticleEditorState | null>(isNew ? emptyArticle() : null);
  const [slugEdited, setSlugEdited] = useState(!isNew);
  const [everPublished, setEverPublished] = useState(false);
  /** The type this version had when it was loaded, and the type of the live published version of the lineage (they differ after a new version changed the type). */
  const [savedType, setSavedType] = useState<string | null>(null);
  const [publishedType, setPublishedType] = useState<string | null>(null);
  const [aliases, setAliases] = useState<string[]>([]);
  /** The rating the Story had when it was loaded; the store shows what was tapped since. */
  const [savedStars, setSavedStars] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationState>({ status: "checking" });
  const [bodyIr, setBodyIr] = useState<unknown>(null);
  const [busy, setBusy] = useState<"save" | "publish" | "unpublish" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [conflictOpen, setConflictOpen] = useState(false);
  const [unpublishOpen, setUnpublishOpen] = useState(false);
  const [publishWarningOpen, setPublishWarningOpen] = useState(false);
  const [previewPopover, setPreviewPopover] = useState<PreviewPopoverTarget | null>(null);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const [mobileTab, setMobileTab] = useState<MobileTab>("preview");
  const [focusedReferenceId, setFocusedReferenceId] = useState<string | null>(null);
  const [lineageId, setLineageId] = useState<string | null>(null);
  const [latestVersion, setLatestVersion] = useState<{ id: string; number: number } | null>(null);
  const latestVersionNumber = latestVersion?.number ?? null;
  const [changeReason, setChangeReason] = useState("");
  const citedKeys = useMemo(() => Object.values(((bodyIr as { papyrus?: { citations?: Record<string, string[]> } } | null)?.papyrus?.citations) ?? {}).flat(), [bodyIr]);
  const { sections: deskSections, loading: deskSectionsLoading, error: deskSectionsError } = useNewsroomDeskSections();
  const deskOptions = useMemo(() => newsroomDeskPickerOptions(deskSections, editor?.section), [deskSections, editor?.section]);
  const [reloadToken, setReloadToken] = useState(0);
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({});
  const [imageUploading, setImageUploading] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [imageNotice, setImageNotice] = useState<string | null>(null);
  const [coverPickerOpen, setCoverPickerOpen] = useState(false);

  const frontMatterRef = useRef<HTMLTextAreaElement | null>(null);
  const bodyRef = useRef<MarkusBodyEditorHandle | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const mediaBackend = useMemo(() => resolveMediaBackend(previewMode), [previewMode]);
  const stockImageClient = useMemo(() => (previewMode ? createDemoStockImageClient() : createLiveStockImageClient(accessTokenFromAmplify)), [previewMode]);
  const validationSequence = useRef(0);

  useEffect(() => {
    if (blocked || isNew) return;
    let cancelled = false;
    backend
      .loadArticle(activeArticleId)
      .then((article) => {
        if (cancelled) return;
        setEditor(stateFromArticle(article));
        setLineageId(article.lineageId ?? null);
        setAliases(article.aliases);
        setSavedStars(article.starRating ?? null);
        setEverPublished(article.everPublished);
        setSavedType(article.type);
        setPublishedType(article.publishedType ?? (article.everPublished ? article.type : null));
        setSlugEdited(true);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(failureMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [activeArticleId, backend, blocked, isNew, reloadToken]);

  const savedItemId = editor?.id ?? null;
  useEffect(() => {
    if (blocked || savedItemId === null) return;
    let cancelled = false;
    mediaBackend
      .listMediaAssets(savedItemId)
      .then(async (assets) => {
        const entries = await Promise.all(
          assets.map(async (asset) => {
            if (!asset.srcPath || !asset.storagePath) return null;
            try {
              return [asset.srcPath, await mediaBackend.imageUrl(asset.storagePath)] as const;
            } catch {
              return null;
            }
          }),
        );
        if (cancelled) return;
        const loaded = Object.fromEntries(entries.filter((entry) => entry !== null));
        setImageUrls((current) => ({ ...loaded, ...current }));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [blocked, mediaBackend, savedItemId]);

  const frontMatterYaml = editor?.frontMatterYaml ?? null;
  const bodyMarkus = editor?.bodyMarkus ?? null;
  const editorialBackend = useMemo(
    () => (demo ? demoEditorialBackend : !previewMode ? graphqlEditorialBackend : null),
    [demo, previewMode],
  );
  const editorial = useEditorialChecks({
    backend: editorialBackend,
    body: bodyMarkus,
    section: editor?.section ?? "",
    itemId: editor?.id ?? null,
  });
  const afterEditorialSave = editorial.afterSave;
  const editorialOpen = useMemo(
    () => (editorial.result ? visibleFindings(editorial.result.findings, editorial.dismissed) : []),
    [editorial.result, editorial.dismissed],
  );
  const editorialMarks = useMemo(() => inlineFindings(editorialOpen), [editorialOpen]);

  useEffect(() => {
    if (frontMatterYaml === null || bodyMarkus === null) return;
    const sequence = ++validationSequence.current;
    setValidation({ status: "checking" });
    const timer = window.setTimeout(() => {
      backend.actions
        .deriveMarkus({ frontMatterYaml, bodyMarkus, includeIr: true })
        .then((result) => {
          if (validationSequence.current !== sequence) return;
          setBodyIr(result.bodyIr ?? null);
          setValidation({ status: "valid" });
        })
        .catch((error: unknown) => {
          if (validationSequence.current !== sequence) return;
          if (error instanceof ContentActionFailure && error.errors.length > 0) {
            setValidation({ status: "invalid", errors: error.errors });
          } else {
            setValidation({ status: "unavailable", message: failureMessage(error) });
          }
        });
    }, VALIDATION_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [backend, frontMatterYaml, bodyMarkus]);

  const dirty = editor?.dirty ?? false;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const patchEditor = useCallback((patch: Partial<NewsroomArticleEditorState>) => {
    setEditor((current) => (current ? { ...current, ...patch, dirty: true } : current));
    setNotice(null);
  }, []);

  const changeFrontMatter = (value: string) => {
    const patch: Partial<NewsroomArticleEditorState> = { frontMatterYaml: value };
    if (!slugEdited && !everPublished) patch.slug = suggestSlug(value);
    patchEditor(patch);
  };

  const changeFrontMatterField = (key: string, value: string) => {
    if (editor) changeFrontMatter(writeFrontMatterText(editor.frontMatterYaml, key, value));
  };

  const goToLine = (location: ErrorLocation) => {
    setMobileTab("preview");
    window.setTimeout(() => {
      const target = location.field === "frontMatterYaml" ? frontMatterRef.current : bodyRef.current;
      if (!target) return;
      const index = location.line ? lineStartIndex(target.value, location.line) : 0;
      target.focus();
      target.setSelectionRange(index, index);
    }, 0);
  };

  const insertImage = async (file: File) => {
    if (!editor || editor.id === null) return;
    setImageUploading(true);
    setImageError(null);
    setImageNotice(null);
    try {
      const uploaded = await uploadArticleImage(mediaBackend, readImageDimensions, {
        itemId: editor.id,
        slug: editor.slug,
        file,
      });
      if (uploaded.directive === null) {
        setImageNotice(`Dark version uploaded as ${uploaded.srcPath}. It replaces the light image in dark mode wherever the light image is used.`);
        return;
      }
      const textarea = bodyRef.current;
      const start = textarea?.selectionStart ?? editor.bodyMarkus.length;
      const end = textarea?.selectionEnd ?? editor.bodyMarkus.length;
      const inserted = insertDirectiveAtSelection(editor.bodyMarkus, start, end, uploaded.directive);
      setImageUrls((current) => ({ ...current, [uploaded.srcPath]: uploaded.imageUrl }));
      patchEditor({ bodyMarkus: inserted.body });
      window.setTimeout(() => {
        const target = bodyRef.current;
        if (!target) return;
        target.focus();
        target.setSelectionRange(inserted.altSelectionStart, inserted.altSelectionStart);
      }, 0);
    } catch (error) {
      setImageError(failureMessage(error));
    } finally {
      setImageUploading(false);
    }
  };

  /** The editor accepted a stock image: copy it in through the same upload as "Insert image", then put it in the draft as the cover. Saving makes the new version. */
  const acceptCover = async (picked: PickedImage) => {
    if (!editor || editor.id === null) return;
    const uploaded = await uploadArticleImage(mediaBackend, readImageDimensions, { itemId: editor.id, slug: editor.slug, file: picked.file });
    const record = coverRecord(picked.candidate, uploaded.srcPath, new Date().toISOString(), picked.pickedBy);
    const directive = coverDirective(uploaded.srcPath, picked.candidate.description || picked.candidate.title, creditLine(picked.candidate));
    const bodyMarkus = bodyWithCover(editor.bodyMarkus, directive, replaceableCoverSources(editor.frontMatterYaml));
    const frontMatterYaml = frontMatterWithCover(editor.frontMatterYaml, record);
    setImageUrls((current) => ({ ...current, [uploaded.srcPath]: uploaded.imageUrl }));
    patchEditor({ bodyMarkus, frontMatterYaml });
    setCoverPickerOpen(false);
    setImageError(null);
    setImageNotice(`Cover set to "${picked.candidate.title}" by ${picked.candidate.creator}. Save the draft to keep it as a new version. A photo has no Night version, so it is shown as it is in dark mode.`);
  };

  useEffect(() => {
    if (!lineageId || isNew) { setLatestVersion(null); return; }
    let cancelled = false;
    loadStoryReportingTrail(lineageId, activeArticleId)
      .then(trail => { if (!cancelled) { const newest = trail.versions[0]; setLatestVersion(newest ? { id: newest.id, number: newest.versionNumber } : null); } })
      .catch(() => { if (!cancelled) setLatestVersion(null); });
    return () => { cancelled = true; };
  }, [activeArticleId, isNew, lineageId, reloadToken]);

  const saveNewVersion = useCallback(async () => {
    if (!editor || editor.id === null) return;
    setBusy("save");
    try {
      const result = await backend.actions.saveItemDraft({
        id: editor.id,
        type: editor.type,
        slug: editor.slug,
        section: editor.section.trim() ? editor.section.trim() : null,
        frontMatterYaml: editor.frontMatterYaml,
        bodyMarkus: editor.bodyMarkus,
        aliases,
        expectedContentHash: editor.contentHash,
        newVersion: true,
        changeReason: changeReason.trim() || null,
      });
      setChangeReason("");
      setActiveArticleId(result.item.id);
      setNotice({ tone: "ok", text: `Saved as version ${result.item.versionNumber ?? ""}.` });
      afterEditorialSave(result.item.id);
    } catch (error) {
      setNotice({ tone: "error", text: failureMessage(error) });
    } finally {
      setBusy(null);
    }
  }, [aliases, backend, changeReason, editor, afterEditorialSave]);

  const decideGeneratedIdea = useCallback(async (record: IdeaDecisionRecord) => {
    if (!editor || editor.id === null) return;
    const frontMatterYaml = writeIdeaDecision(editor.frontMatterYaml, record);
    const result = await backend.actions.saveItemDraft({
      id: editor.id,
      type: editor.type,
      slug: editor.slug,
      section: editor.section.trim() ? editor.section.trim() : null,
      frontMatterYaml,
      bodyMarkus: editor.bodyMarkus,
      aliases,
      expectedContentHash: editor.contentHash,
    });
    setEditor((current) => (current ? { ...current, frontMatterYaml, contentHash: result.item.contentHash, versionNumber: result.item.versionNumber } : current));
    if (!lineageId) return;
    const stage = stageForIdeaDecision(record.decision, getContentItemStageDefinitions().map(definition => definition.key));
    if (!stage) return;
    try {
      await backend.actions.moveStoryStage({ lineageId, stage, reason: record.note || null });
    } catch (error) {
      throw new Error(`The decision is recorded, but the idea could not be moved: ${failureMessage(error)}`);
    }
  }, [aliases, backend, editor, lineageId]);

  const saveDraft = useCallback(async (): Promise<string | null> => {
    if (!editor) return null;
    setBusy("save");
    try {
      const result = await backend.actions.saveItemDraft({
        id: editor.id,
        type: editor.type,
        slug: editor.slug,
        section: editor.section.trim() ? editor.section.trim() : null,
        frontMatterYaml: editor.frontMatterYaml,
        bodyMarkus: editor.bodyMarkus,
        aliases,
        expectedContentHash: editor.contentHash,
      });
      setEditor((current) =>
        current
          ? {
              ...current,
              id: result.item.id,
              contentHash: result.item.contentHash,
              status: result.item.status === "published" ? "published" : "draft",
              versionNumber: result.item.versionNumber,
              slug: result.item.slug,
              dirty: false,
            }
          : current,
      );
      setSavedType(editor.type);
      if (editor.id === null) {
        window.history.replaceState(
          null,
          "",
          getNewsroomNavHref(newsroomHref("articles", result.item.id), demo),
        );
      }
      setNotice({ tone: "ok", text: "Draft saved." });
      afterEditorialSave(result.item.id);
      return result.item.id;
    } catch (error) {
      if (error instanceof ContentActionFailure && error.errors.some((entry) => entry.code === "conflict")) {
        setConflictOpen(true);
      } else if (error instanceof ContentActionFailure && error.errors.some((entry) => entry.line !== null || entry.code.startsWith("markus"))) {
        setValidation({ status: "invalid", errors: error.errors });
      } else {
        setNotice({ tone: "error", text: failureMessage(error) });
      }
      return null;
    } finally {
      setBusy(null);
    }
  }, [aliases, backend, demo, editor, afterEditorialSave]);

  const requestPublish = () => {
    if (editorial.openWarnings.length > 0) {
      setPublishWarningOpen(true);
      return;
    }
    void publish();
  };

  const applyEditorialRewrite = (
    option: { span: { start: number; end: number }; replacement: string; expected: string },
    finding: Parameters<typeof editorial.fixed>[0] | null,
  ) => {
    if (!editor) return;
    const next = applyReplacement(editor.bodyMarkus, option.span, option.expected, option.replacement);
    if (next === null) {
      setNotice({ tone: "info", text: "That text changed since the check. Check again, then apply the rewrite." });
      return;
    }
    patchEditor({ bodyMarkus: next });
    if (finding) editorial.fixed(finding);
    setPreviewPopover(null);
  };

  const editorialActions: FindingActions = {
    onSelect: (finding) => {
      editorial.setActiveFindingId(finding.id);
      if (editorial.inlineResult && finding.excerpt) bodyRef.current?.reveal(finding.span.start, finding.span.end);
    },
    onDismiss: (finding, reason) => {
      editorial.dismiss(finding, reason);
      setPreviewPopover(null);
    },
    onAccept: editorial.accept,
    onSuggest: editorial.suggest,
    onApply: applyEditorialRewrite,
  };

  const publish = async () => {
    setPublishWarningOpen(false);
    if (!editor) return;
    let id = editor.id;
    if (editor.dirty || id === null) {
      id = await saveDraft();
      if (id === null) return;
    }
    setBusy("publish");
    try {
      const result = await backend.actions.publishItem(id);
      setEditor((current) =>
        current ? { ...current, id, status: "published", versionNumber: result.versionNumber } : current,
      );
      setEverPublished(true);
      setSavedType(editor.type);
      setPublishedType(editor.type);
      const base = result.changed
        ? `Published as version ${result.versionNumber ?? "?"}.`
        : `Already published; no changes to publish (version ${result.versionNumber ?? "?"}).`;
      setNotice(result.noPublicPage
        ? { tone: "info", text: `${base} This site built no page for it, so nothing is live: it has no public URL.` }
        : result.typeChangedFrom
          ? { tone: "info", text: `${base} It was live as the type ${result.typeChangedFrom}; its address moved, and the old address redirects.` }
          : { tone: "ok", text: base });
    } catch (error) {
      setNotice({ tone: "error", text: failureMessage(error) });
    } finally {
      setBusy(null);
    }
  };

  const unpublish = async () => {
    if (!editor?.id) return;
    setUnpublishOpen(false);
    setBusy("unpublish");
    try {
      await backend.actions.unpublishItem(editor.id);
      setEditor((current) => (current ? { ...current, status: "draft" } : current));
      setNotice({ tone: "ok", text: "Unpublished. The article is a draft again." });
    } catch (error) {
      setNotice({ tone: "error", text: failureMessage(error) });
    } finally {
      setBusy(null);
    }
  };

  const reloadAfterConflict = () => {
    setConflictOpen(false);
    setLoadError(null);
    setReloadToken((token) => token + 1);
  };

  if (blocked) return <NewsDeskAccessGate shell={session?.shell ?? null} />;

  const listHref = getNewsroomNavHref(newsroomHref("articles"), demo);
  const pageTitle = editor
    ? (isNew && !editor.id ? "New article" : editor.slug || "Article")
    : "Article";

  const body = (() => {
    if (loadError) {
      return (
        <div className="space-y-3">
          <NewsroomOpsStatusBanner tone="error">{loadError}</NewsroomOpsStatusBanner>
          <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }))} href={listHref}>
            Back to articles
          </Link>
        </div>
      );
    }
    if (!editor) {
      return (
        // The same blocks, in the same order and heights, as the loaded editor (toolbar, then fields, tabs and the preview card),
        // so nothing moves when the article arrives. The heights live in newsroom-organizer.css (data-skeleton-*).
        <div aria-label="Loading article" aria-busy="true" className="space-y-4" data-newsroom-article-skeleton role="status">
          <div className="rounded-md bg-muted" data-skeleton-toolbar />
          {!isNew ? <div className="max-w-md rounded-md bg-muted" data-skeleton-stars /> : null}
          <div className="grid gap-6">
            <div className="rounded-md bg-muted" data-skeleton-fields />
            <div className="h-10 w-72 max-w-full rounded-md bg-muted" data-skeleton-tabs />
            <div className="rounded-xl bg-muted" data-skeleton-preview />
          </div>
        </div>
      );
    }

    const slugLocked = everPublished;
    const siteTypes = siteStoryTypes();
    const typeChoices = editorTypeChoices(editor.type, siteTypes.types);
    const address = storyAddress(siteTypes, editor.type, editor.section);
    const liveAddress = publishedType && publishedType !== editor.type ? storyAddress(siteTypes, publishedType, editor.section) : null;
    /** A live Story saved in place is republished at once, so a new type waits for a new version. */
    const typeNeedsNewVersion = editor.status === "published" && savedType !== null && editor.type !== savedType;
    /** Publishing this version would remove the live page: the new type has no page. */
    const publishWouldRemoveLivePage = liveAddress !== null && address.kind === "none";
    /** A Story with no type can be drafted and edited, but the site decides where a page lives from the type, so it cannot be published yet. */
    const typeNotSet = isUntyped(editor.type);
    const invalid = validation.status === "invalid" || validation.status === "unavailable";
    const isOlderVersion = latestVersionNumber !== null && editor.versionNumber !== null && editor.versionNumber < latestVersionNumber;
    const publishBlocked = isOlderVersion || invalid || validation.status === "checking" || busy !== null || !editor.slug.trim() || typeNeedsNewVersion || publishWouldRemoveLivePage || typeNotSet;
    const saveBlocked = isOlderVersion || invalid || busy !== null || !editor.slug.trim() || (!editor.dirty && editor.id !== null) || typeNeedsNewVersion;
    const stagingUrl = stagingPreviewUrl(
      process.env.NEXT_PUBLIC_PAPYRUS_STAGING_URL,
      editor.type,
      editor.slug,
      process.env.NEXT_PUBLIC_PAPYRUS_STAGING_PREVIEW === "static",
    );
    const errors = validation.status === "invalid" ? validation.errors : [];
    const statusLabel =
      editor.status === "published" ? "Published" : "Draft";

    const slugInput = (
      <Input
        aria-label="Slug"
        data-newsroom-article-slug
        disabled={slugLocked}
        onChange={(event) => {
          setSlugEdited(true);
          patchEditor({ slug: event.target.value });
        }}
        value={editor.slug}
      />
    );

    return (
      <TooltipProvider>
        <div className="space-y-4" data-newsroom-article-editor>
          <div className="flex flex-wrap items-center gap-2" data-newsroom-article-toolbar>
            <Link
              aria-label="Back to articles"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "px-2")}
              href={listHref}
            >
              <ArrowLeftIcon aria-hidden="true" />
              Articles
            </Link>
            <Badge data-newsroom-article-status variant={editor.status === "published" ? "secondary" : "muted"}>
              {statusLabel}
            </Badge>
            {editor.versionNumber !== null && editor.status === "published" ? (
              <Badge data-newsroom-article-version variant="outline">{`Version ${editor.versionNumber}`}</Badge>
            ) : null}
            <Badge
              className="min-w-[8.5rem] justify-center"
              data-newsroom-article-validity={validation.status}
              variant={validation.status === "valid" ? "secondary" : invalid ? "outline" : "muted"}
            >
              {validation.status === "valid"
                ? "Valid"
                : validation.status === "invalid"
                  ? `${errors.length} ${errors.length === 1 ? "error" : "errors"}`
                  : validation.status === "unavailable"
                    ? "Validation unavailable"
                    : "Checking…"}
            </Badge>
            {editor.dirty ? <Badge variant="outline">Unsaved changes</Badge> : null}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {stagingUrl ? (
                <a
                  className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                  data-newsroom-article-staging-link
                  href={stagingUrl}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  Preview on staging
                  <ExternalLinkIcon aria-hidden="true" />
                </a>
              ) : null}
              <Button
                data-newsroom-article-save
                disabled={saveBlocked}
                onClick={() => void saveDraft()}
                size="sm"
                type="button"
                variant="outline"
              >
                {busy === "save" ? <Spinner /> : null}
                Save draft
              </Button>
              <Button
                data-newsroom-article-save-version
                disabled={isOlderVersion || invalid || busy !== null || editor.id === null || !editor.dirty}
                onClick={() => void saveNewVersion()}
                size="sm"
                type="button"
                variant="outline"
              >
                Save as new version
              </Button>
              <Button
                data-newsroom-article-publish
                disabled={publishBlocked}
                onClick={requestPublish}
                size="sm"
                type="button"
              >
                {busy === "publish" ? <Spinner /> : null}
                Publish
              </Button>
              {editor.status === "published" ? (
                <Button
                  data-newsroom-article-unpublish
                  disabled={isOlderVersion || busy !== null}
                  onClick={() => setUnpublishOpen(true)}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Unpublish
                </Button>
              ) : null}
            </div>
          </div>

          {notice ? (
            <div data-newsroom-article-notice>
              <NewsroomOpsStatusBanner tone={notice.tone}>{notice.text}</NewsroomOpsStatusBanner>
            </div>
          ) : null}

          {editor.id !== null ? (
            <div className="max-w-md" data-newsroom-article-stars>
              <StarRating
                feedback={stars.feedback(lineageId ?? editor.id)}
                label="Rating · optional"
                onChange={(tapped) => stars.tap(lineageId ?? editor.id!, editor.id!, savedStars, tapped)}
                value={stars.value(lineageId ?? editor.id, savedStars)}
              />
            </div>
          ) : null}

          <div className="grid gap-6">
            <div
              className="min-w-0 space-y-4"
              data-newsroom-article-edit-column
            >
              <div className="grid gap-3" data-feed-flat="" data-feed-surface="" data-newsroom-article-type-field>
                <div className="space-y-1.5 text-sm font-medium" role="group" aria-label="Type">
                  <span className="flex items-center gap-2">
                    Type
                    {typeNotSet ? (
                      <span className="inline-flex items-center gap-1 rounded-[var(--feed-radius-md,8px)] bg-[var(--feed-control)] px-2 py-0.5 text-xs" data-newsroom-article-type-unset>
                        <CircleDashedIcon aria-hidden="true" className="size-3.5" />
                        Not set
                      </span>
                    ) : null}
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {typeChoices.map((type) => (
                      <button
                        aria-pressed={editor.type === type}
                        className={cn(
                          "inline-flex min-h-10 items-center gap-1.5 px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring",
                          isOlderVersion && "opacity-60",
                        )}
                        data-newsroom-article-type={type}
                        disabled={isOlderVersion}
                        key={type}
                        onClick={() => patchEditor({ type })}
                        type="button"
                      >
                        {editor.type === type ? <CheckIcon aria-hidden="true" className="size-4" /> : null}
                        {typeLabel(type)}
                      </button>
                    ))}
                  </div>
                </div>
                {typeNotSet ? (
                  <p className="flex items-start gap-2 rounded-[var(--feed-radius-md,8px)] bg-[var(--feed-control)] p-3 text-sm" data-newsroom-article-type-required role="status">
                    <CircleDashedIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    <span><strong>This Story has no type yet.</strong> You can draft and edit it, but it cannot be published until you choose a type: the site decides where its page lives from the type.</span>
                  </p>
                ) : address.kind === "none" ? (
                  <p className="flex items-start gap-2 rounded-[var(--feed-radius-md,8px)] bg-[var(--feed-control)] p-3 text-sm" data-newsroom-article-no-public-url role="status">
                    <GlobeLockIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    <span><strong>No public URL.</strong> {address.reason} Publishing records it as published, but the site builds no page for it.</span>
                  </p>
                ) : (
                  <p className="flex items-start gap-2 text-sm text-muted-foreground" data-newsroom-article-address>
                    <RouteIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    <span>Published under {describeBase(address.base)}{address.via === "section" ? " (the section decides the address)" : address.via === "root" ? " (no address is declared for this type)" : ""}.</span>
                  </p>
                )}
                {liveAddress && publishedType ? (
                  <p className="flex items-start gap-2 rounded-[var(--feed-radius-md,8px)] bg-[var(--feed-control)] p-3 text-sm" data-newsroom-article-type-move role="status">
                    <RouteIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    <span>
                      <strong>Live as the type {typeLabel(publishedType)}{liveAddress.kind === "route" ? ` under ${describeBase(liveAddress.base)}` : ""}.</strong>{" "}
                      {address.kind === "none"
                        ? `Publishing it as the type ${typeLabel(editor.type)} would remove the live page, so Publish is off. Choose a type the site publishes, or unpublish it.`
                        : `Publishing it as the type ${typeLabel(editor.type)} moves it under ${describeBase(address.base)}; the old address redirects. Until then the live page does not change.`}
                    </span>
                  </p>
                ) : null}
                {typeNeedsNewVersion ? (
                  <p className="rounded-[var(--feed-radius-md,8px)] bg-[var(--feed-control)] p-3 text-sm" data-newsroom-article-type-needs-version role="status">
                    This Story is live. Use Save as new version to change its type: saving it in place would republish it at once.
                  </p>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1 text-sm font-medium">
                  <span>Section</span>
                  <Select
                    onValueChange={(value) => {
                      if (typeof value === "string") patchEditor({ section: value === NO_DESK_VALUE ? "" : value });
                    }}
                    value={deskOptions.some(option => option.value === editor.section) ? editor.section : NO_DESK_VALUE}
                  >
                    <SelectTrigger aria-label="Section" className="w-full" data-newsroom-article-section>
                      <SelectValue>{deskOptions.find(option => option.value === editor.section)?.label ?? "No section"}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_DESK_VALUE}>No section</SelectItem>
                      {(["core", "rotating"] as const).map((kind) => deskOptions.some(option => option.kind === kind) ? (
                        <SelectGroup key={kind}>
                          <SelectLabel>{kind === "core" ? "Core sections" : "Rotating sections"}</SelectLabel>
                          {deskOptions.filter(option => option.kind === kind).map((option) => (
                            <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                          ))}
                        </SelectGroup>
                      ) : null)}
                    </SelectContent>
                  </Select>
                  <small data-newsroom-article-section-status role="status" className="block h-6 overflow-hidden text-xs leading-6">
                    {deskSectionsLoading ? "Loading the site's sections…" : deskSectionsError ? `Could not load the site's sections: ${deskSectionsError}` : ""}
                  </small>
                </label>
                <label className="space-y-1 text-sm font-medium">
                  <span>Slug</span>
                  {slugLocked ? (
                    <Tooltip>
                      <TooltipTrigger render={<span className="block" data-newsroom-article-slug-locked />}>
                        {slugInput}
                      </TooltipTrigger>
                      <TooltipContent>The slug cannot change once the article has been published.</TooltipContent>
                    </Tooltip>
                  ) : (
                    slugInput
                  )}
                </label>
              </div>

                {isOlderVersion ? <p className="newsroom-article-older-version" data-newsroom-article-older-version role="status">
                This is version {editor.versionNumber} of {latestVersionNumber}, shown read-only. <button className="newsroom-article-link-button" onClick={() => setActiveArticleId(latestVersion?.id ?? activeArticleId)} type="button">Open the latest version</button>
              </p> : null}
              {!isOlderVersion ? <SeededFromReferenceNote frontMatterYaml={editor.frontMatterYaml} /> : null}
              {!isNew && editor.id && !isOlderVersion && isGeneratedIdeaFrontMatter(editor.frontMatterYaml) ? (
                <IdeaDecision
                  decidedBy={session?.shell.auth.status === "signedIn" ? session.shell.auth.label : "editor"}
                  frontMatterYaml={editor.frontMatterYaml}
                  key={editor.id}
                  onDecide={decideGeneratedIdea}
                />
              ) : null}
              <div aria-label="Story view" className="newsroom-article-view-toggle" role="group">
              <button aria-pressed={mobileTab === "preview"} className="organizer-header-button" data-newsroom-article-view="preview" onClick={() => setMobileTab("preview")} type="button">Preview</button>
              <button aria-pressed={mobileTab === "edit"} className="organizer-header-button" data-newsroom-article-view="edit" onClick={() => setMobileTab("edit")} type="button">Edit</button>
              <button aria-pressed={mobileTab === "trail"} className="organizer-header-button" data-newsroom-article-view="trail" onClick={() => setMobileTab("trail")} type="button">Messages</button>
              <button aria-pressed={mobileTab === "references"} className="organizer-header-button" data-newsroom-article-view="references" onClick={() => { setFocusedReferenceId(null); setMobileTab("references"); }} type="button">References</button>
            </div>
              {(mobileTab === "trail" || mobileTab === "references") && editor.id ? <StoryReportingTrailView assign={{ sectionKey: deskOptions.some(option => option.value === editor.section.trim()) ? editor.section.trim() : null, storyTitle: readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_TITLE_KEY) || editor.slug }} focusedReferenceId={focusedReferenceId} onShowReference={(referenceId) => { setFocusedReferenceId(referenceId); setMobileTab("references"); }} view={mobileTab === "references" ? "references" : "messages"} citedKeys={citedKeys} demo={previewMode} itemId={editor.id} lineageId={lineageId} onOpenVersion={(versionId) => { setActiveArticleId(versionId); setMobileTab("preview"); }} /> : null}
              <div className={cn("space-y-4", mobileTab === "edit" ? "block" : "hidden")} data-newsroom-article-raw-code>
              <div className="newsroom-article-front-matter-fields" data-newsroom-article-fields>
                <label><span>Title</span><Input data-newsroom-article-field="title" onChange={(event) => changeFrontMatterField(FRONT_MATTER_TITLE_KEY, event.target.value)} value={readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_TITLE_KEY)} /></label>
                <label><span>Subtitle</span><Input data-newsroom-article-field="subtitle" onChange={(event) => changeFrontMatterField(FRONT_MATTER_SUBTITLE_KEY, event.target.value)} placeholder="A line under the headline" value={readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_SUBTITLE_KEY)} /></label>
                <label><span>Blurb</span><Textarea data-newsroom-article-field="blurb" onChange={(event) => changeFrontMatterField(FRONT_MATTER_BLURB_KEY, event.target.value)} placeholder="Two or three lines that describe the story on the board and in listings" rows={3} value={readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_BLURB_KEY)} /></label>
              </div>
              <Input aria-label="What changed in this version" className="max-w-xl" onChange={(event) => setChangeReason(event.target.value)} placeholder="What changed? Recorded when you save as a new version." value={changeReason} />
              <details className="newsroom-article-front-matter" data-newsroom-article-front-matter-details>
                <summary>Front matter (YAML)</summary>
              <label className="block space-y-1 text-sm font-medium">
                <span className="sr-only">Front matter (YAML)</span>
                <Textarea
                  className={TEXTAREA_CLASS}
                  data-newsroom-article-front-matter
                  onChange={(event) => changeFrontMatter(event.target.value)}
                  ref={frontMatterRef}
                  rows={8}
                  spellCheck={false}
                  value={editor.frontMatterYaml}
                />
              </label>
              </details>

              <div className="space-y-1 text-sm font-medium">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="sr-only" htmlFor="newsroom-article-body">Story body</label>
                  <Button
                    data-newsroom-article-insert-image
                    disabled={editor.id === null || imageUploading || busy !== null}
                    onClick={() => imageInputRef.current?.click()}
                    size="xs"
                    type="button"
                    variant="outline"
                  >
                    {imageUploading ? <Spinner /> : <ImagePlusIcon aria-hidden="true" />}
                    Insert image
                  </Button>
                  <Button
                    data-newsroom-article-cover-image
                    disabled={editor.id === null || busy !== null || coverPickerOpen}
                    onClick={() => setCoverPickerOpen(true)}
                    size="xs"
                    type="button"
                    variant="outline"
                  >
                    <ImagesIcon aria-hidden="true" />
                    Cover image
                  </Button>
                  <input
                    accept="image/*"
                    aria-label="Image file"
                    className="hidden"
                    data-newsroom-article-image-input
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      event.target.value = "";
                      if (file) void insertImage(file);
                    }}
                    ref={imageInputRef}
                    type="file"
                  />
                </div>
                {editor.id === null ? (
                  <p className="text-xs font-normal text-muted-foreground" data-newsroom-article-image-hint>
                    Save the draft once to enable image upload.
                  </p>
                ) : null}
                <p className="text-xs font-normal text-muted-foreground" data-newsroom-article-image-dark-hint>
                  For a dark-mode picture, insert the light image first, then upload a file named like it with .dark before the extension (figure.png and figure.dark.png). Same proportions, please.
                </p>
                {coverPickerOpen && editor.id !== null ? (
                  <CoverImagePicker
                    client={stockImageClient}
                    onClose={() => setCoverPickerOpen(false)}
                    onPicked={acceptCover}
                    summary={readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_BLURB_KEY) || readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_SUBTITLE_KEY) || editor.bodyMarkus.split("\n").filter((line) => !/^\s*(:::?|#)/.test(line)).join(" ").slice(0, 600)}
                    title={readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_TITLE_KEY) || editor.slug}
                  />
                ) : null}
                {imageNotice ? (
                  <p className="text-xs font-normal text-muted-foreground" data-newsroom-article-image-notice role="status">
                    {imageNotice}
                  </p>
                ) : null}
                {imageError ? (
                  <p className="text-xs font-normal text-destructive" data-newsroom-article-image-error role="alert">
                    {imageError}
                  </p>
                ) : null}
                <MarkusBodyEditor
                  activeFindingId={editorial.activeFindingId}
                  findings={editorialMarks}
                  onChange={(value) => patchEditor({ bodyMarkus: value })}
                  onFindingClick={editorial.setActiveFindingId}
                  onSelectionChange={editorial.setSelection}
                  ref={bodyRef}
                  value={editor.bodyMarkus}
                />
              </div>

              {editorial.enabled ? (
                <EditorialFindingsPanel
                  {...editorialActions}
                  activeFindingId={editorial.activeFindingId}
                  dismissed={editorial.dismissed}
                  onCheck={() => void editorial.check()}
                  result={editorial.result}
                  selection={editorial.selection}
                  status={editorial.status}
                />
              ) : null}

              {validation.status === "unavailable" ? (
                <NewsroomOpsStatusBanner tone="error">{validation.message}</NewsroomOpsStatusBanner>
              ) : null}
              {errors.length > 0 ? (
                <ul
                  aria-label="Validation errors"
                  className="space-y-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm"
                  data-newsroom-article-errors
                >
                  {errors.map((error, index) => {
                    const location = locateError(error, editor.frontMatterYaml);
                    return (
                      <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1" data-newsroom-article-error={error.code} key={`${error.code}-${index}`}>
                        <code className="font-mono text-xs">{error.code}</code>
                        <span className="min-w-0 flex-1 break-words">{error.message}</span>
                        <Button
                          onClick={() => goToLine(location)}
                          size="xs"
                          type="button"
                          variant="outline"
                        >
                          {location.line
                            ? `${location.field === "frontMatterYaml" ? "front matter " : ""}line ${location.line}`
                            : location.field === "frontMatterYaml" ? "front matter" : "body"}
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
              </div>
            </div>

            <div
              className={cn("min-w-0", mobileTab === "preview" ? "block" : "hidden")}
              data-newsroom-article-preview-column
            >
              <div className="relative rounded-xl border border-border bg-card p-4" data-newsroom-article-preview ref={previewRef}>
                {(readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_SUBTITLE_KEY) || readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_BLURB_KEY)) ? (
                  <div className="newsroom-article-summary" data-newsroom-article-summary>
                    {readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_SUBTITLE_KEY) ? <p className="newsroom-article-subtitle">{readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_SUBTITLE_KEY)}</p> : null}
                    {readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_BLURB_KEY) ? <p className="newsroom-article-blurb">{readFrontMatterText(editor.frontMatterYaml, FRONT_MATTER_BLURB_KEY)}</p> : null}
                  </div>
                ) : null}
                {invalid && bodyIr ? (
                  <p className="mb-2 text-xs text-muted-foreground">Showing the last valid version.</p>
                ) : null}
                {bodyIr ? (
                  <MarkusIrPreview
                    bodyIr={bodyIr}
                    editorial={
                      editorial.inlineResult
                        ? {
                            result: editorial.inlineResult,
                            findings: editorialOpen,
                            activeFindingIds: previewPopover?.kind === "findings" ? previewPopover.findingIds : editorial.activeFindingId ? [editorial.activeFindingId] : [],
                            onOpenMark: (findingIds, anchor) => {
                              editorial.setActiveFindingId(findingIds[0] ?? null);
                              setPreviewPopover({ kind: "findings", findingIds, anchor: anchor.getBoundingClientRect() });
                            },
                            onSelectSource: (source, anchor) => setPreviewPopover({ kind: "selection", source, anchor }),
                          }
                        : undefined
                    }
                    imageUrls={imageUrls}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {invalid ? "Fix the errors to see a preview." : "The preview appears once the markup is valid."}
                  </p>
                )}
                {previewPopover && editorial.enabled ? (
                  <EditorialPreviewPopover
                    actions={editorialActions}
                    body={editor.bodyMarkus}
                    container={previewRef.current}
                    findings={editorialOpen}
                    key={previewPopover.kind === "findings" ? previewPopover.findingIds.join() : `${previewPopover.source.start}-${previewPopover.source.end}`}
                    onClose={() => setPreviewPopover(null)}
                    target={previewPopover}
                  />
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <Dialog onOpenChange={setConflictOpen} open={conflictOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Someone else saved this article</DialogTitle>
              <DialogDescription>
                The article changed since you opened it. Reload to get the latest version; your unsaved edits here will be replaced.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button data-newsroom-article-conflict-reload onClick={reloadAfterConflict} type="button">
                Reload
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog onOpenChange={setPublishWarningOpen} open={publishWarningOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Publish with open editorial findings?</DialogTitle>
              <DialogDescription>
                {editorial.openWarnings.length === 1
                  ? "One editorial finding is still open."
                  : `${editorial.openWarnings.length} editorial findings are still open.`}{" "}
                Findings are advice: you can publish anyway.
              </DialogDescription>
            </DialogHeader>
            <ul className="max-h-48 list-disc space-y-1 overflow-auto pl-5 text-sm" data-newsroom-article-publish-warnings>
              {editorial.openWarnings.slice(0, 8).map((finding) => (
                <li key={finding.id}>{finding.message}{finding.excerpt ? `: “${finding.excerpt}”` : ""}</li>
              ))}
            </ul>
            <DialogFooter>
              <Button onClick={() => setPublishWarningOpen(false)} type="button" variant="outline">Keep editing</Button>
              <Button data-newsroom-article-publish-anyway onClick={() => void publish()} type="button">Publish anyway</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Dialog onOpenChange={setUnpublishOpen} open={unpublishOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Unpublish this article?</DialogTitle>
              <DialogDescription>
                The article is removed from the published site and becomes a draft again.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button onClick={() => setUnpublishOpen(false)} type="button" variant="outline">Cancel</Button>
              <Button data-newsroom-article-unpublish-confirm onClick={() => void unpublish()} type="button">
                Unpublish
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </TooltipProvider>
    );
  })();

  if (embedded) return <div className="newsroom-embedded-article">{body}</div>;

  return (
    <NewsroomOpsShell
      activeTab="articles"
      appTitle={SITE_BRAND.appTitle}
      backHref="/"
      backLabel={SITE_BRAND.backToHomeLabel}
      demo={demo}
      headerActions={demo ? <Badge variant="outline">Demo</Badge> : null}
      pageTitle={pageTitle}
    >
      {body}
    </NewsroomOpsShell>
  );
}
