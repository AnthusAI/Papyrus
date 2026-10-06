"use client";

import { ArrowLeftIcon, ExternalLinkIcon } from "lucide-react";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ContentActionFailure, type ContentActionError } from "../lib/content-actions-client";
import { newsroomHref } from "../lib/newsroom-base-path";
import {
  ARTICLE_TYPES,
  emptyArticle,
  locateError,
  resolveArticlesBackend,
  stagingPreviewUrl,
  suggestSlug,
  uniqueSections,
  type ArticlesBackend,
  type EditableArticle,
  type ErrorLocation,
  type NewsroomArticleEditorState,
} from "../lib/newsroom-articles";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { SITE_BRAND } from "../lib/site-brand";
import { cn } from "../lib/utils";
import { MarkusIrPreview } from "./markus-ir-preview";
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
type MobileTab = "edit" | "preview";

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

export function NewsroomArticleEditor({ articleId, demo }: { articleId: string; demo: boolean }) {
  const session = useOptionalNewsDeskClient();
  const blocked = !demo && articlesAccessBlocked(session?.shell.phase);
  const backend: ArticlesBackend = useMemo(() => resolveArticlesBackend(demo), [demo]);
  const isNew = articleId === "new";

  const [editor, setEditor] = useState<NewsroomArticleEditorState | null>(isNew ? emptyArticle() : null);
  const [slugEdited, setSlugEdited] = useState(!isNew);
  const [everPublished, setEverPublished] = useState(false);
  const [aliases, setAliases] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationState>({ status: "checking" });
  const [bodyIr, setBodyIr] = useState<unknown>(null);
  const [busy, setBusy] = useState<"save" | "publish" | "unpublish" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [conflictOpen, setConflictOpen] = useState(false);
  const [unpublishOpen, setUnpublishOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("edit");
  const [sections, setSections] = useState<string[]>([]);
  const [reloadToken, setReloadToken] = useState(0);

  const frontMatterRef = useRef<HTMLTextAreaElement | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);
  const validationSequence = useRef(0);

  useEffect(() => {
    if (blocked || isNew) return;
    let cancelled = false;
    backend
      .loadArticle(articleId)
      .then((article) => {
        if (cancelled) return;
        setEditor(stateFromArticle(article));
        setAliases(article.aliases);
        setEverPublished(article.everPublished);
        setSlugEdited(true);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(failureMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [articleId, backend, blocked, isNew, reloadToken]);

  useEffect(() => {
    if (blocked) return;
    let cancelled = false;
    backend
      .listRows()
      .then((rows) => {
        if (!cancelled) setSections(uniqueSections(rows));
      })
      .catch(() => {
        if (!cancelled) setSections([]);
      });
    return () => {
      cancelled = true;
    };
  }, [backend, blocked]);

  const frontMatterYaml = editor?.frontMatterYaml ?? null;
  const bodyMarkus = editor?.bodyMarkus ?? null;

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

  const goToLine = (location: ErrorLocation) => {
    setMobileTab("edit");
    window.setTimeout(() => {
      const target = location.field === "frontMatterYaml" ? frontMatterRef.current : bodyRef.current;
      if (!target) return;
      const index = location.line ? lineStartIndex(target.value, location.line) : 0;
      target.focus();
      target.setSelectionRange(index, index);
    }, 0);
  };

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
      if (editor.id === null) {
        window.history.replaceState(
          null,
          "",
          getNewsroomNavHref(newsroomHref("articles", result.item.id), demo),
        );
      }
      setNotice({ tone: "ok", text: "Draft saved." });
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
  }, [aliases, backend, demo, editor]);

  const publish = async () => {
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
      setNotice({
        tone: "ok",
        text: result.changed
          ? `Published as version ${result.versionNumber ?? "?"}.`
          : `Already published; no changes to publish (version ${result.versionNumber ?? "?"}).`,
      });
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
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Loading article…
        </div>
      );
    }

    const slugLocked = everPublished;
    const invalid = validation.status === "invalid" || validation.status === "unavailable";
    const publishBlocked = invalid || validation.status === "checking" || busy !== null || !editor.slug.trim();
    const saveBlocked = invalid || busy !== null || !editor.slug.trim() || (!editor.dirty && editor.id !== null);
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
                data-newsroom-article-publish
                disabled={publishBlocked}
                onClick={() => void publish()}
                size="sm"
                type="button"
              >
                {busy === "publish" ? <Spinner /> : null}
                Publish
              </Button>
              {editor.status === "published" ? (
                <Button
                  data-newsroom-article-unpublish
                  disabled={busy !== null}
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

          <Tabs className="lg:hidden" defaultValue="edit" onValueChange={(value) => setMobileTab(value as MobileTab)} value={mobileTab}>
            <TabsList>
              <TabsTrigger className="min-w-[6rem]" value="edit">Edit</TabsTrigger>
              <TabsTrigger className="min-w-[6rem]" value="preview">Preview</TabsTrigger>
            </TabsList>
          </Tabs>

          <div className="grid gap-6 lg:grid-cols-2">
            <div
              className={cn("min-w-0 space-y-4", mobileTab === "edit" ? "block" : "hidden", "lg:block")}
              data-newsroom-article-edit-column
            >
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="space-y-1 text-sm font-medium">
                  <span>Type</span>
                  <Select
                    onValueChange={(value) => {
                      if (typeof value === "string") patchEditor({ type: value });
                    }}
                    value={editor.type}
                  >
                    <SelectTrigger aria-label="Type" className="w-full" data-newsroom-article-type>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ARTICLE_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>{type}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="space-y-1 text-sm font-medium">
                  <span>Section</span>
                  <Input
                    data-newsroom-article-section
                    list="newsroom-article-sections"
                    onChange={(event) => patchEditor({ section: event.target.value })}
                    value={editor.section}
                  />
                  <datalist id="newsroom-article-sections">
                    {sections.map((section) => (
                      <option key={section} value={section} />
                    ))}
                  </datalist>
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

              <label className="block space-y-1 text-sm font-medium">
                <span>Front matter (YAML)</span>
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

              <label className="block space-y-1 text-sm font-medium">
                <span>Body (Markus)</span>
                <Textarea
                  className={TEXTAREA_CLASS}
                  data-newsroom-article-body
                  onChange={(event) => patchEditor({ bodyMarkus: event.target.value })}
                  ref={bodyRef}
                  rows={28}
                  spellCheck={false}
                  value={editor.bodyMarkus}
                />
              </label>

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

            <div
              className={cn("min-w-0", mobileTab === "preview" ? "block" : "hidden", "lg:block")}
              data-newsroom-article-preview-column
            >
              <div className="rounded-xl border border-border bg-card p-4" data-newsroom-article-preview>
                <p className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  Preview
                </p>
                {invalid && bodyIr ? (
                  <p className="mb-2 text-xs text-muted-foreground">Showing the last valid version.</p>
                ) : null}
                {bodyIr ? (
                  <MarkusIrPreview bodyIr={bodyIr} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {invalid ? "Fix the errors to see a preview." : "The preview appears once the markup is valid."}
                  </p>
                )}
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
