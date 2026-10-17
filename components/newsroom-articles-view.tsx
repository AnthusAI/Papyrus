"use client";

import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SITE_BRAND } from "../lib/site-brand";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { newsroomHref } from "../lib/newsroom-base-path";
import {
  resolveArticlesBackend,
  rowStatusLabel,
  type NewsroomArticleRow,
} from "../lib/newsroom-articles";
import { cn } from "../lib/utils";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";

type ArticleFilter = "all" | "drafts" | "published";

export function articlesAccessBlocked(phase: string | undefined): boolean {
  return phase === undefined || phase === "checkingAccess" || phase === "signedOut" || phase === "forbidden" || phase === "error";
}

export function NewsroomArticlesView({ demo }: { demo: boolean }) {
  const session = useOptionalNewsDeskClient();
  const blocked = !demo && articlesAccessBlocked(session?.shell.phase);
  const [rows, setRows] = useState<NewsroomArticleRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ArticleFilter>("all");

  useEffect(() => {
    if (blocked) return;
    let cancelled = false;
    resolveArticlesBackend(demo)
      .listRows()
      .then((loaded) => {
        if (!cancelled) setRows(loaded);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "Could not load articles.");
      });
    return () => {
      cancelled = true;
    };
  }, [blocked, demo]);

  const visibleRows = useMemo(() => {
    if (!rows) return [];
    if (filter === "drafts") return rows.filter((row) => row.status === "draft");
    if (filter === "published") return rows.filter((row) => row.status === "published");
    return rows;
  }, [filter, rows]);

  if (blocked) return <NewsDeskAccessGate shell={session?.shell ?? null} />;

  return (
    <NewsroomOpsShell
      activeTab="articles"
      appTitle={SITE_BRAND.appTitle}
      backHref="/"
      backLabel={SITE_BRAND.backToHomeLabel}
      demo={demo}
      headerActions={(
        <>
          {demo ? <Badge variant="outline">Demo</Badge> : null}
          <Link
            className={cn(buttonVariants({ size: "sm" }))}
            data-newsroom-article-new
            href={getNewsroomNavHref(newsroomHref("articles", "new"), demo)}
          >
            <PlusIcon aria-hidden="true" />
            New article
          </Link>
        </>
      )}
      pageTitle="Articles"
    >
      <div className="space-y-4" data-newsroom-articles>
        <Tabs defaultValue="all" onValueChange={(value) => setFilter(value as ArticleFilter)} value={filter}>
          <TabsList>
            <TabsTrigger className="min-w-[5.5rem]" value="all">All</TabsTrigger>
            <TabsTrigger className="min-w-[5.5rem]" value="drafts">Drafts</TabsTrigger>
            <TabsTrigger className="min-w-[5.5rem]" value="published">Published</TabsTrigger>
          </TabsList>
        </Tabs>
        {loadError ? <NewsroomOpsStatusBanner tone="error">{loadError}</NewsroomOpsStatusBanner> : null}
        {rows === null && !loadError ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> Loading articles…
          </div>
        ) : null}
        {rows !== null && visibleRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing here yet.</p>
        ) : null}
        <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-newsroom-articles-list>
          {visibleRows.map((row) => (
            <li key={row.id}>
              <Link
                className="flex flex-col gap-1 px-4 py-3 hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
                data-newsroom-article-row={row.slug}
                href={getNewsroomNavHref(newsroomHref("articles", row.id), demo)}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{row.title}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {row.slug}
                    {row.section ? ` · ${row.section}` : ""}
                    {row.type !== "article" ? ` · ${row.type}` : ""}
                  </span>
                </span>
                <Badge
                  data-newsroom-article-status
                  variant={row.status === "draft" ? "muted" : row.pending ? "outline" : "secondary"}
                >
                  {rowStatusLabel(row)}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </NewsroomOpsShell>
  );
}
