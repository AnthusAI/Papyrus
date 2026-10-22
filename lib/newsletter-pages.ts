import { NextResponse } from "next/server";

/**
 * The small server-rendered pages of the newsletter plugin (confirm prompt, confirmed, expired).
 * Plain HTML, no scripts. They are drawn inside the site's own chrome (the projected newsletter shell: the site's head,
 * stylesheets, header and footer) and fall back to a self-contained page themed from the plugin's public settings. Every
 * dynamic value is escaped, the token never reaches a link, and the pages are never cached or indexed.
 */
export type NewsletterPageTheme = { accent: string; text: string; background: string; surface: string; muted: string; fontFamily: string };

export const DEFAULT_PAGE_THEME: NewsletterPageTheme = {
  accent: "#1a4d8f",
  text: "#1b1b1b",
  background: "#ffffff",
  surface: "#f4f4f4",
  muted: "#555555",
  fontFamily: "Georgia, 'Times New Roman', serif",
};

const UNSAFE_CSS = /[<>{};"\\`]|url\(|expression\(|@import/i;
const MAXIMUM_LISTS_SHOWN = 20;

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => `&#${character.charCodeAt(0)};`);
}

/** Theme tokens from `custom.papyrusPlugins.newsletter.theme`; a missing or unsafe value falls back to the default. */
export function pageTheme(raw: unknown): NewsletterPageTheme {
  const theme: NewsletterPageTheme = { ...DEFAULT_PAGE_THEME };
  if (typeof raw !== "object" || raw === null) return theme;
  for (const key of Object.keys(theme) as Array<keyof NewsletterPageTheme>) {
    const value = (raw as Record<string, unknown>)[key];
    if (typeof value === "string" && value.length > 0 && value.length <= 200 && !UNSAFE_CSS.test(value)) theme[key] = value;
  }
  return theme;
}

export type FormSpec = {
  action: string;
  /** Hidden fields, such as the token. */
  hidden: Record<string, string>;
  checkboxes?: Array<{ name: string; value: string; label: string; checked: boolean }>;
  /** Every button says what it does in words. `secondary` only changes how it looks. */
  buttons: Array<{ label: string; name?: string; value?: string; secondary?: boolean }>;
};

export type PageContent = {
  siteName: string;
  theme: NewsletterPageTheme;
  heading: string;
  /** A short status line shown above the text (for example "Saved"), as words. */
  notice?: string;
  paragraphs: string[];
  lists?: string[];
  forms?: FormSpec[];
  links?: Array<{ href: string; label: string }>;
};

function renderForm(form: FormSpec): string {
  const hidden = Object.entries(form.hidden)
    .map(([name, value]) => `<input type="hidden" name="${escapeHtml(name)}" value="${escapeHtml(value)}">`)
    .join("");
  const boxes = (form.checkboxes ?? [])
    .map(
      (box, index) =>
        `<p class="markus-newsletter-list"><input type="checkbox" id="c${index}" name="${escapeHtml(box.name)}" value="${escapeHtml(box.value)}"${box.checked ? " checked" : ""}> <label for="c${index}">${escapeHtml(box.label)}</label></p>`,
    )
    .join("");
  const buttons = form.buttons
    .map(
      (button) =>
        `<button type="submit" class="markus-button"${button.secondary ? ' data-variant="secondary"' : ""}${button.name ? ` name="${escapeHtml(button.name)}" value="${escapeHtml(button.value ?? "")}"` : ""}>${escapeHtml(button.label)}</button>`,
    )
    .join(" ");
  return `<form class="markus-newsletter-form" method="post" action="${escapeHtml(form.action)}">${hidden}${boxes}<p class="markus-actions">${buttons}</p></form>`;
}

/**
 * The content of a page, in the standard front end's own classes (`markus-document`, `markus-button`, `markus-actions`), so
 * inside the site's chrome it takes the site's typography, colours, buttons and focus rings from the site's stylesheets.
 */
export function renderBody(page: PageContent): string {
  const lists = (page.lists ?? []).slice(0, MAXIMUM_LISTS_SHOWN);
  const links = (page.links ?? []).map((link) => `<p><a href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a></p>`).join("\n");
  return `<div class="markus-document markus-newsletter-page" data-newsletter-page>
<h1>${escapeHtml(page.heading)}</h1>
${page.notice ? `<p class="markus-newsletter-notice" role="status">${escapeHtml(page.notice)}</p>` : ""}
${page.paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("\n")}
${lists.length > 0 ? `<ul>${lists.map((name) => `<li>${escapeHtml(name)}</li>`).join("")}</ul>` : ""}
${(page.forms ?? []).map(renderForm).join("\n")}
${links}
</div>`;
}

/** The self-contained page, for a site whose chrome shell cannot be fetched. Themed from the plugin's settings. */
export function renderPage(page: PageContent): string {
  const { theme } = page;
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${escapeHtml(page.heading)} - ${escapeHtml(page.siteName)}</title>
<style>
body{margin:0;background:${theme.background};color:${theme.text};font-family:${theme.fontFamily};line-height:1.5}
main{max-width:34rem;margin:0 auto;padding:3rem 1.25rem}
.site{color:${theme.muted};font-size:.95rem;margin:0 0 1.5rem}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 1rem}
.markus-newsletter-notice{background:${theme.surface};border-left:4px solid ${theme.accent};padding:.5rem .75rem;font-weight:bold}
ul{background:${theme.surface};margin:1rem 0;padding:.75rem 1.25rem 1rem 2rem}
.markus-newsletter-list{margin:.6rem 0}
input[type=checkbox]{width:1.1rem;height:1.1rem;vertical-align:middle}
.markus-actions{margin:1.25rem 0}
.markus-button{background:${theme.accent};color:#fff;border:2px solid ${theme.accent};font:inherit;font-weight:bold;padding:.7rem 1.4rem;cursor:pointer;border-radius:4px;margin:0 .5rem .5rem 0}
.markus-button[data-variant=secondary]{background:${theme.background};color:${theme.accent}}
.markus-button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid ${theme.text};outline-offset:2px}
a{color:${theme.accent}}
</style></head><body><main>
<p class="site">${escapeHtml(page.siteName)}</p>
${renderBody(page)}
</main></body></html>`;
}

/** Where the standard projector writes the chrome shell when the newsletter plugin is enabled. */
export const SHELL_PATH = "/_plugins/newsletter-shell/index.html";
export const SHELL_MARKER = "<!--papyrus:newsletter-content-->";
export const SHELL_TTL_MS = 5 * 60 * 1000;
const SHELL_FAILURE_TTL_MS = 30 * 1000;
const SHELL_MAXIMUM_CHARACTERS = 512 * 1024;
const SHELL_TIMEOUT_MS = 3000;

export type ShellFetcher = (url: string) => Promise<{ status: number; contentType: string; text: string }>;

export interface ShellOptions {
  fetchShell?: ShellFetcher;
  /** Milliseconds; for tests. */
  now?: () => number;
}

async function fetchOverHttp(url: string): Promise<{ status: number; contentType: string; text: string }> {
  const response = await fetch(url, { headers: { accept: "text/html" }, redirect: "manual", signal: AbortSignal.timeout(SHELL_TIMEOUT_MS) });
  return { status: response.status, contentType: response.headers.get("content-type") ?? "", text: await response.text() };
}

/**
 * The shell as a template: the site's own page (full head, header, footer) with one content marker. Scripts are removed
 * (these pages run none, and their content security policy forbids them), and the canonical and og:url links, which name
 * the shell, are removed. Null when the page is not a usable shell.
 */
export function prepareShell(html: string): string | null {
  if (html.length > SHELL_MAXIMUM_CHARACTERS || html.split(SHELL_MARKER).length !== 2) return null;
  return html
    .replace(/<script\b[\s\S]*?<\/script\s*>/gi, "")
    .replace(/<link\b[^>]*\brel=["']canonical["'][^>]*>\s*/gi, "")
    .replace(/<meta\b[^>]*\bproperty=["']og:url["'][^>]*>\s*/gi, "");
}

type ShellEntry = { template: string | null; at: number };
const shells = new Map<string, ShellEntry>();
const fetching = new Map<string, Promise<string | null>>();

export function clearShellCache(): void {
  shells.clear();
  fetching.clear();
}

/**
 * The prepared shell of the site at `origin`, cached in memory for five minutes. A failed fetch keeps serving the last good
 * shell, or answers null (the caller falls back to the self-contained page), and is not retried for 30 seconds.
 */
export async function loadShell(origin: string, options: ShellOptions = {}): Promise<string | null> {
  const now = (options.now ?? Date.now)();
  const cached = shells.get(origin);
  if (cached && now - cached.at < (cached.template ? SHELL_TTL_MS : SHELL_FAILURE_TTL_MS)) return cached.template;
  const running = fetching.get(origin);
  if (running) return running;
  const attempt = (async () => {
    let template: string | null = null;
    try {
      const response = await (options.fetchShell ?? fetchOverHttp)(new URL(SHELL_PATH, origin).toString());
      if (response.status === 200 && /html/i.test(response.contentType)) template = prepareShell(response.text);
    } catch {
      template = null;
    }
    // A failure keeps the last good shell; the retry clock restarts either way.
    const kept = template ?? cached?.template ?? null;
    shells.set(origin, { template: kept, at: now });
    return kept;
  })().finally(() => fetching.delete(origin));
  fetching.set(origin, attempt);
  return attempt;
}

/** The page inside the site's chrome: the shell's title replaced and its marker replaced by the page content. */
export function renderShellPage(template: string, page: PageContent): string {
  const title = `${escapeHtml(page.heading)} - ${escapeHtml(page.siteName)}`;
  return template.replace(/<title>[\s\S]*?<\/title>/i, () => `<title>${title}</title>`).replace(SHELL_MARKER, () => renderBody(page));
}

export const PAGE_HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "cache-control": "no-store",
  "referrer-policy": "same-origin",
  "x-content-type-options": "nosniff",
  "x-robots-tag": "noindex",
  "content-security-policy":
    "default-src 'none'; style-src 'self' 'unsafe-inline' https:; font-src 'self' data: https:; img-src 'self' data: https:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
} as const;

/** `shell` is the prepared shell of the site (see `loadShell`); without one the self-contained page is sent. */
export function pageResponse(page: PageContent, status = 200, shell: string | null = null): NextResponse {
  return new NextResponse(shell ? renderShellPage(shell, page) : renderPage(page), { status, headers: PAGE_HEADERS });
}

export const CONFIRM_PATH = "/api/newsletter/confirm";

type Base = Pick<PageContent, "siteName" | "theme">;
const home = (base: Base) => ({ href: "/", label: `Back to ${base.siteName}` });

export function confirmPromptPage(base: Base, lists: string[], token: string): PageContent {
  return {
    ...base,
    heading: "Confirm your subscription",
    paragraphs: [`Press the button to start getting email from ${base.siteName}.${lists.length > 0 ? " You are signing up for:" : ""}`],
    lists,
    forms: [{ action: CONFIRM_PATH, hidden: { t: token }, buttons: [{ label: "Confirm subscription" }] }],
  };
}

export function confirmedPage(base: Base, lists: string[], preferencesHref?: string): PageContent {
  return {
    ...base,
    heading: "You are subscribed",
    paragraphs: [lists.length > 0 ? "Thank you. You will get:" : "Thank you. Your subscription is confirmed."],
    lists,
    links: [...(preferencesHref ? [{ href: preferencesHref, label: "Manage your subscriptions" }] : []), home(base)],
  };
}

export function expiredPage(base: Base): PageContent {
  return {
    ...base,
    heading: "This link has expired",
    paragraphs: [
      "This confirmation link has expired or was already used. If you already confirmed, you are all set.",
      "If you did not finish signing up, go back to the site and sign up again to get a new link.",
    ],
    links: [home(base)],
  };
}

export function crossSitePage(base: Base): PageContent {
  return {
    ...base,
    heading: "That did not go through",
    paragraphs: ["This form was not sent from this site, so nothing was changed. Open the link in your email again and use the button on the page."],
    links: [home(base)],
  };
}

export function unavailablePage(base: Base): PageContent {
  return {
    ...base,
    heading: "Something went wrong",
    paragraphs: ["We could not complete this just now. Open the link in your email again in a minute."],
    links: [home(base)],
  };
}

export const UNSUBSCRIBE_PATH = "/api/newsletter/unsubscribe";
export const PREFERENCES_PATH = "/api/newsletter/preferences";

export function preferencesHref(token: string): string {
  return `${PREFERENCES_PATH}?t=${encodeURIComponent(token)}`;
}

export function invalidManagePage(base: Base): PageContent {
  return {
    ...base,
    heading: "This link is not valid",
    paragraphs: ["This link is not valid, or the subscription it belongs to has been deleted. Use the link in a recent email from us."],
    links: [home(base)],
  };
}

export function unsubscribePromptPage(base: Base, token: string, listId: string | null, listName: string | null): PageContent {
  return {
    ...base,
    heading: "Unsubscribe",
    paragraphs: [listName ? `Stop getting "${listName}" from ${base.siteName}?` : `Stop getting all email from ${base.siteName}?`],
    forms: [
      {
        action: UNSUBSCRIBE_PATH,
        hidden: { t: token, ...(listId ? { l: listId } : {}), page: "1" },
        buttons: [{ label: listName ? "Unsubscribe from this list" : "Unsubscribe from everything" }],
      },
    ],
    links: [{ href: preferencesHref(token), label: "Choose which lists you get instead" }],
  };
}

export function unsubscribedPage(base: Base, names: string[], token: string | null): PageContent {
  return {
    ...base,
    heading: "You are unsubscribed",
    paragraphs: [names.length > 0 ? `You will no longer get these from ${base.siteName}:` : `You will no longer get this email from ${base.siteName}.`],
    lists: names,
    links: [...(token ? [{ href: preferencesHref(token), label: "Change your mind? Manage your subscriptions" }] : []), home(base)],
  };
}

export type PreferenceList = { id: string; name: string; description: string; subscribed: boolean };

export function preferencesPage(base: Base, input: { token: string; email: string; lists: PreferenceList[]; notice?: string }): PageContent {
  return {
    ...base,
    heading: "Your subscriptions",
    notice: input.notice,
    paragraphs: [`Email preferences for ${input.email}. Tick the lists you want.`],
    forms: [
      {
        action: PREFERENCES_PATH,
        hidden: { t: input.token },
        checkboxes: input.lists.map((list) => ({
          name: "l",
          value: list.id,
          label: list.description ? `${list.name}: ${list.description}` : list.name,
          checked: list.subscribed,
        })),
        buttons: [
          { label: "Save preferences", name: "action", value: "save" },
          { label: "Unsubscribe from everything", name: "action", value: "unsubscribe_all", secondary: true },
          { label: "Delete my data", name: "action", value: "delete", secondary: true },
        ],
      },
    ],
    links: [home(base)],
  };
}

export function deleteConfirmPage(base: Base, token: string): PageContent {
  return {
    ...base,
    heading: "Delete your data?",
    paragraphs: [
      `This erases your address and everything ${base.siteName} holds about your subscriptions. You will not get any more email. This cannot be undone.`,
    ],
    forms: [
      {
        action: PREFERENCES_PATH,
        hidden: { t: token, action: "delete", confirm: "1" },
        buttons: [{ label: "Yes, delete my data" }],
      },
    ],
    links: [{ href: preferencesHref(token), label: "No, go back" }],
  };
}

export function deletedPage(base: Base): PageContent {
  return {
    ...base,
    heading: "Your data is deleted",
    paragraphs: ["Your address and subscriptions have been erased. You will not get any more email from us."],
    links: [home(base)],
  };
}
