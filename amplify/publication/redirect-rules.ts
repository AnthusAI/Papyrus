import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

/** One pattern redirect as the edge function reads it: regex, target with $1..$9, status, excluded paths. */
export type EdgeRedirectRule = { p: string; t: string; s: number; x: string[] };

/** Mirrors DIRECTORY_HTML_PATTERN and DIRECTORY_SLASH_PATTERN in standard/config.py. */
const DIRECTORY_HTML_PATTERN = "^/(?!(?:.*/)?index\\.html$)(.+)\\.html$";
const DIRECTORY_SLASH_PATTERN = "^/((?:[^/]+/)*[^/.]+)$";

const START_MARKER = "/*PAPYRUS_PATTERN_RULES*/";
const END_MARKER = "/*END_PAPYRUS_PATTERN_RULES*/";

type ProjectionRedirects = { patterns?: { pattern: string; to: string; status?: number; except?: string[] }[] };
type ProjectionSettings = { site?: unknown; urls?: { style?: string }; redirects?: ProjectionRedirects; agents?: { markdown?: boolean } };

/**
 * The pattern rules a site declares in projection.json: its `redirects.patterns`, plus, for
 * `urls.style: "directory"`, `/x.html` to `/x/`. Mirrors `StandardSettings.edge_rules` in Python.
 */
export function edgeRulesFromSettings(settings: ProjectionSettings): EdgeRedirectRule[] {
  const rules = (settings.redirects?.patterns ?? []).map((rule) => ({
    p: rule.pattern,
    t: rule.to,
    s: rule.status ?? 301,
    x: rule.except ?? [],
  }));
  if (settings.urls?.style === "directory") {
    // /x.html to /x/ (a directory index file such as /x/index.html is served as it is), then /x to /x/.
    rules.push({ p: DIRECTORY_HTML_PATTERN, t: "/$1/", s: 301, x: ["/404.html"] });
    rules.push({ p: DIRECTORY_SLASH_PATTERN, t: "/$1/", s: 301, x: ["/404"] });
  }
  return rules;
}

/** A standard-front-end site publishes Markdown twins unless it turns `agents.markdown` off. */
export function negotiatesMarkdown(settings: ProjectionSettings): boolean {
  return settings.site !== undefined && settings.agents?.markdown !== false;
}

/** A directory-style site keeps a page's Markdown twin at `/x/index.md`; the edge then serves a bare `/x.md` from there. */
export function usesDirectoryTwins(settings: ProjectionSettings): boolean {
  return negotiatesMarkdown(settings) && settings.urls?.style === "directory";
}

export type EdgeConfig = { rules: EdgeRedirectRule[]; negotiateMarkdown: boolean; directoryTwins: boolean };

export function readEdgeConfig(staticDir: string | undefined, baseDirectory: string = process.cwd()): EdgeConfig {
  if (staticDir === undefined) return { rules: [], negotiateMarkdown: false, directoryTwins: false };
  const settingsPath = resolve(baseDirectory, staticDir, "projection.json");
  if (!existsSync(settingsPath)) return { rules: [], negotiateMarkdown: false, directoryTwins: false };
  const settings = JSON.parse(readFileSync(settingsPath, "utf8")) as ProjectionSettings;
  return { rules: edgeRulesFromSettings(settings), negotiateMarkdown: negotiatesMarkdown(settings), directoryTwins: usesDirectoryTwins(settings) };
}

export function readEdgeRules(staticDir: string | undefined, baseDirectory: string = process.cwd()): EdgeRedirectRule[] {
  return readEdgeConfig(staticDir, baseDirectory).rules;
}

const NEGOTIATE_START = "/*PAPYRUS_NEGOTIATE_MARKDOWN*/";
const NEGOTIATE_END = "/*END_PAPYRUS_NEGOTIATE_MARKDOWN*/";
const TWINS_START = "/*PAPYRUS_DIRECTORY_TWINS*/";
const TWINS_END = "/*END_PAPYRUS_DIRECTORY_TWINS*/";

function spliceFlag(source: string, start: string, end: string, label: string): string {
  const from = source.indexOf(start);
  const to = source.indexOf(end);
  if (from === -1 || to === -1 || to < from) {
    throw new Error(`redirect function source has no ${label} markers`);
  }
  return source.slice(0, from + start.length) + "true" + source.slice(to);
}

/** The CloudFront Function source with the site's pattern rules and Markdown negotiation flag spliced in. */
export function compileRedirectFunctionSource(
  source: string,
  rules: EdgeRedirectRule[],
  options: { negotiateMarkdown?: boolean; directoryTwins?: boolean } = {},
): string {
  const start = source.indexOf(START_MARKER);
  const end = source.indexOf(END_MARKER);
  if (start === -1 || end === -1 || end < start) {
    throw new Error("redirect function source has no pattern-rule markers");
  }
  let compiled = rules.length === 0 ? source : source.slice(0, start + START_MARKER.length) + JSON.stringify(rules) + source.slice(end);
  if (options.negotiateMarkdown === true) {
    compiled = spliceFlag(compiled, NEGOTIATE_START, NEGOTIATE_END, "markdown negotiation");
  }
  if (options.directoryTwins === true) {
    compiled = spliceFlag(compiled, TWINS_START, TWINS_END, "directory twin");
  }
  return compiled;
}
