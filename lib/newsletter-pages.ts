import { NextResponse } from "next/server";

/**
 * The small server-rendered pages of the newsletter plugin (confirm prompt, confirmed, expired).
 * Plain HTML, no scripts, themed from the plugin's public settings. Every dynamic value is escaped, the token never
 * reaches a link, and the pages are never cached or indexed.
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

export type PageContent = {
  siteName: string;
  theme: NewsletterPageTheme;
  heading: string;
  paragraphs: string[];
  lists?: string[];
  /** A POST form with one hidden token field and a submit button. */
  form?: { action: string; token: string; button: string };
  link?: { href: string; label: string };
};

export function renderPage(page: PageContent): string {
  const { theme } = page;
  const lists = (page.lists ?? []).slice(0, MAXIMUM_LISTS_SHOWN);
  const form = page.form
    ? `<form method="post" action="${escapeHtml(page.form.action)}"><input type="hidden" name="t" value="${escapeHtml(page.form.token)}"><button type="submit">${escapeHtml(page.form.button)}</button></form>`
    : "";
  const link = page.link ? `<p><a href="${escapeHtml(page.link.href)}">${escapeHtml(page.link.label)}</a></p>` : "";
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><meta name="referrer" content="no-referrer">
<title>${escapeHtml(page.heading)} - ${escapeHtml(page.siteName)}</title>
<style>
body{margin:0;background:${theme.background};color:${theme.text};font-family:${theme.fontFamily};line-height:1.5}
main{max-width:34rem;margin:0 auto;padding:3rem 1.25rem}
.site{color:${theme.muted};font-size:.95rem;margin:0 0 1.5rem}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 1rem}
ul{background:${theme.surface};margin:1rem 0;padding:.75rem 1.25rem 1rem 2rem}
button{background:${theme.accent};color:#fff;border:2px solid ${theme.accent};font:inherit;font-weight:bold;padding:.7rem 1.4rem;cursor:pointer;border-radius:4px}
button:focus-visible,a:focus-visible{outline:3px solid ${theme.text};outline-offset:2px}
a{color:${theme.accent}}
</style></head><body><main>
<p class="site">${escapeHtml(page.siteName)}</p>
<h1>${escapeHtml(page.heading)}</h1>
${page.paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("\n")}
${lists.length > 0 ? `<ul>${lists.map((name) => `<li>${escapeHtml(name)}</li>`).join("")}</ul>` : ""}
${form}
${link}
</main></body></html>`;
}

export const PAGE_HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
} as const;

export function pageResponse(page: PageContent, status = 200): NextResponse {
  return new NextResponse(renderPage(page), { status, headers: PAGE_HEADERS });
}

export const CONFIRM_PATH = "/api/newsletter/confirm";

export function confirmPromptPage(base: Pick<PageContent, "siteName" | "theme">, lists: string[], token: string): PageContent {
  return {
    ...base,
    heading: "Confirm your subscription",
    paragraphs: [
      `Press the button to start getting email from ${base.siteName}.${lists.length > 0 ? " You are signing up for:" : ""}`,
    ],
    lists,
    form: { action: CONFIRM_PATH, token, button: "Confirm subscription" },
  };
}

export function confirmedPage(base: Pick<PageContent, "siteName" | "theme">, lists: string[]): PageContent {
  return {
    ...base,
    heading: "You are subscribed",
    paragraphs: [lists.length > 0 ? "Thank you. You will get:" : "Thank you. Your subscription is confirmed."],
    lists,
    link: { href: "/", label: `Back to ${base.siteName}` },
  };
}

export function expiredPage(base: Pick<PageContent, "siteName" | "theme">): PageContent {
  return {
    ...base,
    heading: "This link has expired",
    paragraphs: [
      "This confirmation link has expired or was already used. If you already confirmed, you are all set.",
      "If you did not finish signing up, go back to the site and sign up again to get a new link.",
    ],
    link: { href: "/", label: `Back to ${base.siteName}` },
  };
}

export function unavailablePage(base: Pick<PageContent, "siteName" | "theme">): PageContent {
  return {
    ...base,
    heading: "Something went wrong",
    paragraphs: ["We could not complete this just now. Open the link in your email again in a minute."],
    link: { href: "/", label: `Back to ${base.siteName}` },
  };
}
