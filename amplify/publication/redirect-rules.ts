import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

/** One pattern redirect as the edge function reads it: regex, target with $1..$9, status, excluded paths. */
export type EdgeRedirectRule = { p: string; t: string; s: number; x: string[] };

const START_MARKER = "/*PAPYRUS_PATTERN_RULES*/";
const END_MARKER = "/*END_PAPYRUS_PATTERN_RULES*/";

type ProjectionRedirects = { patterns?: { pattern: string; to: string; status?: number; except?: string[] }[] };
type ProjectionSettings = { urls?: { style?: string }; redirects?: ProjectionRedirects };

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
    rules.push({ p: "^/(.+)\\.html$", t: "/$1/", s: 301, x: ["/404.html"] });
  }
  return rules;
}

export function readEdgeRules(staticDir: string | undefined, baseDirectory: string = process.cwd()): EdgeRedirectRule[] {
  if (staticDir === undefined) return [];
  const settingsPath = resolve(baseDirectory, staticDir, "projection.json");
  if (!existsSync(settingsPath)) return [];
  return edgeRulesFromSettings(JSON.parse(readFileSync(settingsPath, "utf8")) as ProjectionSettings);
}

/** The CloudFront Function source with the site's pattern rules spliced in; the source unchanged when there are none. */
export function compileRedirectFunctionSource(source: string, rules: EdgeRedirectRule[]): string {
  const start = source.indexOf(START_MARKER);
  const end = source.indexOf(END_MARKER);
  if (start === -1 || end === -1 || end < start) {
    throw new Error("redirect function source has no pattern-rule markers");
  }
  if (rules.length === 0) return source;
  const literal = JSON.stringify(rules);
  return source.slice(0, start + START_MARKER.length) + literal + source.slice(end);
}
