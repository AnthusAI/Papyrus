"use client";

import { SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "../lib/utils";

import { useEffect, useId, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { BookOpen, ClipboardList, Menu, Search, MessagesSquare, PanelLeftClose, PanelLeftOpen, Settings, UserRound, LogIn, LogOut } from "lucide-react";
import { ORGANIZER_NAV_GROUPS, ORGANIZER_PRIMARY_NAV, ORGANIZER_SETTINGS_DESTINATION } from "../lib/newsroom-organizer-nav";
import { browserPathToInternalNewsroomPath } from "../lib/newsroom-base-path";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { SITE_BRAND } from "../lib/site-brand";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { ReaderAuthControl } from "./reader-auth-control";
import { ProspectusAccountChooser, useProspectusAccountSummary } from "./prospectus-account-chooser";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetTrigger } from "./ui/sheet";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuGroup, DropdownMenuLabel, DropdownMenuItem, DropdownMenuSeparator } from "./ui/dropdown-menu";
import "./newsroom-organizer.css";
import { NewsroomThemeFonts, useNewsroomThemeAttributes } from "./newsroom-theme";

export type NewsroomNavCount = {
  count: number | null;
  missing?: boolean;
  visible?: boolean;
};

export type NewsroomOpsShellProps = {
  activeTab: string;
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

/** The standard place to search the knowledge base; the Search page is the results page. */
function OrganizerSearch({ demo }: { demo: boolean }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [text, setText] = useState(searchParams.get("q") ?? "");
  return <form className="organizer-search" role="search" onSubmit={event => {
    event.preventDefault();
    const query = text.trim();
    if (query) router.push(getNewsroomNavHref(`/newsroom/search?q=${encodeURIComponent(query)}`, demo));
  }}>
    <Search size={14} aria-hidden="true" />
    <input aria-label="Search the knowledge base" data-newsroom-search type="search" onChange={event => setText(event.target.value)} placeholder="Search" value={text} />
  </form>;
}

const ICONS = { articles: ClipboardList, references: BookOpen, messages: MessagesSquare };

/** Navigation is a presentation layer; existing route and server authorization still own access. */
function Navigation({ activePath, demo, admin, surface, onNavigate }: { activePath: string; demo: boolean; admin: boolean; surface: string; onNavigate?: () => void }) {
  const id = useId();
  const all = ORGANIZER_NAV_GROUPS.flatMap(group => group.items);
  const active = all.filter(item => [item.path, ...(item.alsoActiveOnPaths ?? [])].some(candidate => activePath === candidate || (candidate !== "/newsroom" && activePath.startsWith(candidate + "/")))).sort((a, b) => b.path.length - a.path.length)[0]?.key;
  return <nav className="organizer-destinations" aria-label={surface === "sidebar" ? "Newsroom" : "All workspaces"}>
    {ORGANIZER_NAV_GROUPS.map((group, index) => <section key={group.title} aria-labelledby={`${id}-${index}`}>
      <h3 id={`${id}-${index}`}>{group.title}</h3>
      {group.items.filter(item => item.access !== "admin" || admin).map(item => <Link key={item.key}
        href={getNewsroomNavHref(item.path, demo)} onClick={onNavigate} aria-label={item.label}
        aria-current={active === item.key ? "page" : undefined} aria-describedby={`${id}-${item.key}`}
        data-news-desk-tab={item.key}>
        <strong>{item.label}</strong><small id={`${id}-${item.key}`}>{item.description}</small>
      </Link>)}
    </section>)}
  </nav>;
}

function Account({ placement }: { placement: "sidebar" | "header" }) {
  const session = useOptionalNewsDeskClient();
  const auth = session?.shell.auth ?? { status: "loading" as const, label: "Checking sign-in" };
  const [open, setOpen] = useState(false);
  const accountSummary = useProspectusAccountSummary();
  useEffect(() => {
    const media = matchMedia("(max-width: 900px)");
    const close = () => setOpen(false);
    media.addEventListener("change", close);
    return () => media.removeEventListener("change", close);
  }, []);
  const themeAttributes = useNewsroomThemeAttributes();
  return <DropdownMenu open={open} onOpenChange={setOpen}>
    <DropdownMenuTrigger id={`organizer-account-trigger-${placement}`} className={`organizer-account organizer-account-${placement}`} aria-label="Account menu" title="Account menu">
      <UserRound size={18} aria-hidden="true" /><span><strong>{auth.label}</strong><small>{accountSummary ?? (auth.status === "signedIn" ? "Account & preferences" : auth.status === "signedOut" ? "Not signed in" : "Checking session")}</small></span>
    </DropdownMenuTrigger>
    <DropdownMenuContent className="organizer-account-popup" {...themeAttributes} side={placement === "sidebar" ? "top" : "bottom"} align="end">
      <DropdownMenuGroup>
        <DropdownMenuLabel>{auth.label}</DropdownMenuLabel><DropdownMenuSeparator />
        <ProspectusAccountChooser />
        <DropdownMenuItem render={<Link href={getNewsroomNavHref(ORGANIZER_SETTINGS_DESTINATION.path)} />}><Settings aria-hidden="true" />{ORGANIZER_SETTINGS_DESTINATION.label}</DropdownMenuItem>
        <ReaderAuthControl authState={auth} renderAction={({ disabled, onClick, signedIn }) => <DropdownMenuItem disabled={disabled} closeOnClick={false} onClick={onClick}>
          {signedIn ? <LogOut aria-hidden="true" /> : <LogIn aria-hidden="true" />}{signedIn ? "Sign out" : "Sign in"}
        </DropdownMenuItem>} />
      </DropdownMenuGroup>
    </DropdownMenuContent>
  </DropdownMenu>;
}

export function NewsroomOpsShell({ activeTab, appTitle, backHref = "/", backLabel, children, demo = false, headerActions, pageTitle, showNavigation = true }: NewsroomOpsShellProps) {
  const pathname = usePathname();
  const themeAttributes = useNewsroomThemeAttributes();
  const session = useOptionalNewsDeskClient();
  const admin = demo || session?.shell.dashboard?.canManageUsers === true;
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [loadedPreference, setLoadedPreference] = useState(false);
  const preferenceKey = `papyrus.cms.sidebar.v1.${SITE_BRAND.id}`;
  useEffect(() => {
    try { setCollapsed(localStorage.getItem(preferenceKey) === "true"); } catch { /* Optional browser preference. */ }
    setLoadedPreference(true);
  }, [preferenceKey]);
  useEffect(() => { if (loadedPreference) try { localStorage.setItem(preferenceKey, String(collapsed)); } catch { /* Controls still work without storage. */ } }, [collapsed, loadedPreference, preferenceKey]);
  useEffect(() => { setMenuOpen(false); }, [pathname]);
  useEffect(() => {
    const media = matchMedia("(max-width: 900px)");
    let previousFocus: Element | null = null;
    let frame = 0;
    const remember = () => { if (document.activeElement !== document.body) previousFocus = document.activeElement; };
    const change = () => {
      const active = document.activeElement === document.body ? previousFocus : document.activeElement;
      if (!(active instanceof HTMLElement)) return;
      if (!media.matches) setMenuOpen(false);
      const selector = active.closest(".organizer-account, .organizer-account-popup") ? ".organizer-account"
        : media.matches && active.closest(".organizer-sidebar, .organizer-toggle") ? ".organizer-more"
        : !media.matches && active.closest(".organizer-bottom-nav, .organizer-menu") ? ".organizer-toggle" : null;
      if (!selector) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (document.activeElement === active || document.activeElement === document.body || !(document.activeElement as HTMLElement)?.getClientRects().length)
          Array.from(document.querySelectorAll<HTMLElement>(selector)).find(element => element.getClientRects().length)?.focus();
      });
    };
    document.addEventListener("focusin", remember);
    media.addEventListener("change", change);
    return () => { document.removeEventListener("focusin", remember); media.removeEventListener("change", change); cancelAnimationFrame(frame); };
  }, []);
  const activePath = browserPathToInternalNewsroomPath(pathname ?? "/newsroom");
  const sidebarToggleLabel = collapsed ? "Expand sidebar" : "Collapse sidebar";
  const sidebarToggle = <button type="button" className="organizer-toggle" title={sidebarToggleLabel}
    aria-label={sidebarToggleLabel} aria-expanded={!collapsed} aria-controls="organizer-sidebar" onClick={() => setCollapsed(value => !value)}>
    {collapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
  </button>;
  return <div className="newsroom-organizer" {...themeAttributes} data-news-desk data-newsroom-ops-shell="true" data-newsroom-chrome="organizer" data-sidebar-collapsed={collapsed || !showNavigation ? "true" : "false"}>
    <NewsroomThemeFonts />
    {showNavigation && <aside className="organizer-sidebar" hidden={collapsed} id="organizer-sidebar">
      <div className="organizer-sidebar-head">
        <Link className="organizer-brand" href={getNewsroomNavHref("/newsroom", demo)}>{SITE_BRAND.components?.NewsroomLogo ? <SITE_BRAND.components.NewsroomLogo className="organizer-brand-logo" /> : appTitle}<small>The newsroom</small></Link>
        {sidebarToggle}
      </div>
      <Navigation activePath={activePath} demo={demo} admin={admin} surface="sidebar" />
      <Account placement="sidebar" />
    </aside>}
    <div className="organizer-workspace">
      <header className="organizer-topbar" data-newsroom-ops-topbar>
        {showNavigation && collapsed && sidebarToggle}
        <Link className="organizer-masthead" href={backHref} title={backLabel}>{appTitle}</Link>
        <h1 data-newsroom-ops-title>{pageTitle}</h1><OrganizerSearch demo={demo} /><div className="organizer-header-actions">{headerActions}</div><Account placement="header" />
      </header>
      <main className="organizer-main">{demo && <p className="organizer-demo-notice">Demo workspace · synthetic examples</p>}{children}</main>
    </div>
    {showNavigation && <nav className="organizer-bottom-nav" aria-label="Primary newsroom navigation"><ul>
      {ORGANIZER_PRIMARY_NAV.map(item => { const Icon = ICONS[item.key as keyof typeof ICONS]; return <li key={item.key}><Link
        href={getNewsroomNavHref(item.path, demo)} title={item.description} aria-label={item.label} aria-current={activeTab === item.key ? "page" : undefined}>
        <Icon size={18} aria-hidden="true" /><span>{item.label}</span></Link></li>; })}
      <li><Sheet open={menuOpen} onOpenChange={setMenuOpen}><SheetTrigger className="organizer-more" aria-label="More"><Menu size={18} aria-hidden="true" /><span>More</span></SheetTrigger>
        <SheetContent side="bottom" className="organizer-menu" {...themeAttributes}><SheetHeader><SheetTitle>Newsroom</SheetTitle><SheetDescription>Workspaces and administration</SheetDescription></SheetHeader>
          <Navigation activePath={activePath} demo={demo} admin={admin} surface="menu" onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet></li>
    </ul></nav>}
  </div>;
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
