"use client";

import {
  BookOpenIcon,
  ClipboardListIcon,
  LayoutGridIcon,
  MenuIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  getNewsroomNavHref,
  NEWSROOM_MOBILE_PRIMARY_NAV,
  NEWSROOM_OPS_NAV,
  type NewsroomNavTabId,
} from "../lib/newsroom-nav";
import { cn } from "../lib/utils";

export type NewsroomNavCount = {
  count: number | null;
  missing?: boolean;
  visible?: boolean;
};

type NewsroomOpsShellProps = {
  activeTab: NewsroomNavTabId | string;
  appTitle: string;
  backHref?: string;
  backLabel: string;
  children: ReactNode;
  demo?: boolean;
  headerActions?: ReactNode;
  pageTitle: ReactNode;
  showNavigation?: boolean;
  tabCounts?: Partial<Record<string, NewsroomNavCount>>;
};

const MOBILE_TAB_ICONS: Record<string, typeof LayoutGridIcon> = {
  overview: LayoutGridIcon,
  assignments: ClipboardListIcon,
  references: BookOpenIcon,
};

function formatCountLabel(count: number | null, missing?: boolean): string {
  if (missing) return "?";
  if (count == null) return "…";
  if (count >= 1000) return `${Math.round(count / 100) / 10}k`;
  return String(count);
}

function NavCountBadge({
  countState,
}: {
  countState?: NewsroomNavCount;
}) {
  if (!countState || countState.visible === false) return null;
  return (
    <Badge
      className="newsroom-nav-count min-w-7 px-1.5"
      data-newsroom-nav-count
      variant={countState.missing ? "outline" : "secondary"}
    >
      {formatCountLabel(countState.count, countState.missing)}
    </Badge>
  );
}

function SidebarNavLink({
  active,
  countState,
  demo,
  item,
  onNavigate,
}: {
  active: boolean;
  countState?: NewsroomNavCount;
  demo?: boolean;
  item: (typeof NEWSROOM_OPS_NAV)[number];
  onNavigate?: () => void;
}) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={cn(
        buttonVariants({ variant: active ? "default" : "ghost", size: "default" }),
        "h-auto min-h-11 w-full justify-start gap-3 px-3 py-2.5 text-left font-normal",
        active && "shadow-sm",
      )}
      data-news-desk-tab={item.id}
      href={getNewsroomNavHref(item.href, demo)}
      onClick={onNavigate}
    >
      <NavCountBadge countState={countState} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{item.label}</span>
        <span className="block text-xs text-muted-foreground">{item.detail}</span>
      </span>
    </Link>
  );
}

export function NewsroomOpsShell({
  activeTab,
  appTitle,
  backHref = "/",
  backLabel,
  children,
  demo = false,
  headerActions,
  pageTitle,
  showNavigation = true,
  tabCounts = {},
}: NewsroomOpsShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const resolvedActiveTab = activeTab === "desks" ? "topics" : activeTab;
  const mobilePrimary = useMemo(() => NEWSROOM_MOBILE_PRIMARY_NAV, []);

  return (
    <div
      className="flex h-dvh max-h-dvh flex-col overflow-hidden bg-background text-foreground"
      data-news-desk
      data-newsroom-chrome="app"
      data-newsroom-ops-shell="true"
    >
      <header
        className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card/50 px-3 sm:px-4"
        data-newsroom-ops-topbar
      >
        <Link
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "shrink-0 px-2")}
          href={backHref}
        >
          {backLabel}
        </Link>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {appTitle}
          </p>
          <h1 className="truncate text-base font-semibold tracking-tight text-foreground" data-newsroom-ops-title>
            {pageTitle}
          </h1>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">{headerActions}</div>
      </header>

      <div className="flex min-h-0 flex-1">
        {showNavigation ? (
          <aside
            aria-label="Newsroom sections"
            className="hidden w-64 shrink-0 flex-col border-r border-border bg-muted/20 md:flex"
            data-newsroom-ops-sidebar
          >
            <ScrollArea className="min-h-0 flex-1 p-3">
              <nav className="flex flex-col gap-1">
                {NEWSROOM_OPS_NAV.map((item) => (
                  <SidebarNavLink
                    active={resolvedActiveTab === item.id}
                    countState={tabCounts[item.id]}
                    demo={demo}
                    item={item}
                    key={item.id}
                  />
                ))}
              </nav>
            </ScrollArea>
          </aside>
        ) : null}

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <ScrollArea className="min-h-0 flex-1">
            <div className="mx-auto w-full max-w-6xl p-4 sm:p-6">{children}</div>
          </ScrollArea>
        </main>
      </div>

      {showNavigation ? (
        <nav
          aria-label="Primary newsroom navigation"
          className="shrink-0 border-t border-border bg-card/95 pb-[max(env(safe-area-inset-bottom),0.35rem)] pt-1 md:hidden"
          data-newsroom-ops-bottom-nav
        >
          <ul className="grid grid-cols-4 gap-1 px-2">
            {mobilePrimary.map((item) => {
              const Icon = MOBILE_TAB_ICONS[item.id] ?? LayoutGridIcon;
              const active = resolvedActiveTab === item.id;
              return (
                <li key={item.id}>
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl px-1 py-2 text-[0.68rem] font-medium",
                      active ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground",
                    )}
                    data-news-desk-tab={item.id}
                    href={getNewsroomNavHref(item.href, demo)}
                  >
                    <Icon className="size-4" aria-hidden="true" />
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
            <li>
              <Sheet onOpenChange={setMenuOpen} open={menuOpen}>
                <SheetTrigger
                  className={cn(
                    "flex min-h-14 w-full flex-col items-center justify-center gap-1 rounded-xl px-1 py-2 text-[0.68rem] font-medium text-muted-foreground",
                  )}
                >
                  <MenuIcon className="size-4" aria-hidden="true" />
                  <span>More</span>
                </SheetTrigger>
                <SheetContent className="gap-0 p-0" side="bottom">
                  <SheetHeader className="border-b border-border px-4 py-4">
                    <SheetTitle>All sections</SheetTitle>
                  </SheetHeader>
                  <ScrollArea className="max-h-[60dvh] p-3">
                    <div className="flex flex-col gap-1">
                      {NEWSROOM_OPS_NAV.map((item) => (
                        <SidebarNavLink
                          active={resolvedActiveTab === item.id}
                          countState={tabCounts[item.id]}
                          demo={demo}
                          item={item}
                          key={item.id}
                          onNavigate={() => setMenuOpen(false)}
                        />
                      ))}
                    </div>
                  </ScrollArea>
                </SheetContent>
              </Sheet>
            </li>
          </ul>
        </nav>
      ) : null}
    </div>
  );
}

export function NewsroomOpsSearchButton({
  disabled,
  onPress,
}: {
  disabled?: boolean;
  onPress?: () => void;
}) {
  return (
    <Button
      aria-label="Search knowledge base"
      disabled={disabled}
      onClick={onPress}
      size="icon-sm"
      type="button"
      variant="outline"
    >
      <SearchIcon className="size-4" />
    </Button>
  );
}

export function NewsroomOpsStatusBanner({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "error" | "info" | "ok";
}) {
  return (
    <div
      className={cn(
        "mb-4 rounded-xl border px-3 py-2 text-sm",
        tone === "error" && "border-destructive/30 bg-destructive/10 text-destructive",
        tone === "ok" && "border-primary/20 bg-primary/10 text-foreground",
        tone === "info" && "border-border bg-muted/40 text-foreground",
      )}
      role="status"
    >
      {children}
    </div>
  );
}

export function NewsroomOpsSectionIntro({
  description,
  title,
}: {
  description: string;
  title: string;
}) {
  return (
    <div className="mb-5 space-y-1">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>
      <Separator className="mt-4" />
    </div>
  );
}
