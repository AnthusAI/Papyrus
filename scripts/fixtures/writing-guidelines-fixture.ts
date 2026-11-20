/**
 * An in-browser stand-in for the guidelines door, for the Writing guidelines page's browser test only: guidelines_get, resolve, diff, save and history for the
 * writing kind, kept in memory as sets of guideline files, with the same layering rule the real resolver uses for the fields the fixture has (prose adds, choices
 * win unless locked) and the refusals the real reader gives for a rule file with problems. It reads and writes nothing outside the page.
 */
import { FIELD_FILES, fileText } from "../../lib/guidelines/guideline-files";
type Doc = Record<string, any>;
type Files = Record<string, string>;
type Version = { itemId: string; versionNumber: number; files: Files; by: string; at: string; reason: string };

export const SITE_DOCUMENT: Doc = {
  schemaVersion: 2,
  voice: { name: "Plain newsroom" },
  audience: "Readers who build and run AI systems at work.",
  editorialAim: "Explain what changed and why it matters, with evidence.",
  tone: ["Plain and specific.", "Calm, never breathless."],
  sentenceStyle: ["Short sentences. One idea each."],
  lexicon: { prefer: ["people"], avoid: ["leverage", "game-changing"] },
  glossary: [{ term: "Papyrus", use: "Papyrus", avoid: ["the CMS"] }],
  bodyMarkus: "Lead with the news. Name the source in the first paragraph.",
  exemplars: [],
  locked: ["audience"],
  constraints: [{ id: "no-hype", text: "Never describe a product as revolutionary." }],
};
const SECTION_DOCUMENT: Doc = { schemaVersion: 2, tone: ["Warmer in the Culture section."], lexicon: { avoid: ["synergy"] } };

export const SECTIONS = [{ key: "ai", name: "AI" }, { key: "culture", name: "Culture" }];
export const STORIES = [
  { lineageId: "story-1", title: "How the newsroom checks a claim" }, { lineageId: "story-2", title: "A week of agent mistakes" },
  { lineageId: "story-3", title: "What a good headline does" },
];

const iso = (day: number) => `2026-11-0${day}T12:00:00.000Z`;

const FIXTURE_RULES: Record<string, { description: string; severity: string; avoid?: string[]; pattern?: string[]; body: string }> = {
  "plain-claims": { description: "Claims are plain and sourced.", severity: "warn", avoid: ["revolutionary", "world-class"], pattern: ["\\bvery unique\\b"], body: "Say what happened. Name who says so.\n" },
  "source-first": { description: "Name the source before the claim.", severity: "error", body: "A reader should know where a claim comes from before they read it.\n" },
  "reading-notes": { description: "Notes for people reading drafts.", severity: "guidance", body: "Read the lede aloud.\n" },
};
const ruleFile = (name: string, rule: (typeof FIXTURE_RULES)[string], section: string | null) =>
  fileText({ id: `urn:uuid:00000000-0000-4000-8000-${String(Object.keys(FIXTURE_RULES).indexOf(name)).padStart(12, "0")}`, type: "papyrus:Guideline", name, description: rule.description, kind: "writing",
    scope: section ? `section/${section}` : "publication", severity: rule.severity, ...(rule.avoid ? { avoid: rule.avoid } : {}), ...(rule.pattern ? { pattern: rule.pattern } : {}) }, rule.body);

/** The files of a document view, as `field_files.files_from_document` writes them. */
export function filesFromDocument(document: Doc, section: string | null = null, rules: string[] = []): Files {
  const files: Files = {};
  for (const [key, value] of Object.entries(document)) {
    const field = FIELD_FILES.find((item) => item.key === key);
    if (key === "schemaVersion" || !field) continue;
    const body = field.form === "text" ? `${value}\n` : field.form === "bullets" ? (value as string[]).map((item) => `- ${item}\n`).join("") : `\`\`\`json\n${JSON.stringify(value, null, 2)}\n\`\`\`\n`;
    files[`${field.name}/GUIDELINE.md`] = fileText({ id: `urn:uuid:fixture-${section ?? "site"}-${field.name}`, type: "papyrus:Guideline", name: field.name, description: `${field.label} in the writing guidelines.`, kind: "writing",
      scope: section ? `section/${section}` : "publication", severity: "guidance" }, body);
  }
  for (const name of rules) files[`${name}/GUIDELINE.md`] = ruleFile(name, FIXTURE_RULES[name], section);
  return files;
}

const FRONT = /^---\n([\s\S]*?)\n---\n([\s\S]*)$/;
/** The document view of a set: the field files read back by their form. */
export function documentFromFiles(files: Files): Doc {
  const document: Doc = { schemaVersion: 2 };
  for (const field of FIELD_FILES) {
    const body = FRONT.exec(files[`${field.name}/GUIDELINE.md`] ?? "")?.[2];
    if (body === undefined) continue;
    document[field.key] = field.form === "text" ? body.replace(/\n$/, "") : field.form === "bullets" ? body.split("\n").filter((line) => line.startsWith("- ")).map((line) => line.slice(2)) : JSON.parse(/```json\n([\s\S]*)\n```/.exec(body)![1]);
  }
  return document;
}

/** What the real reader refuses in a rule file, by file and key. */
function problemsOf(files: Files): { guideline: string; key: string; message: string }[] {
  const problems: { guideline: string; key: string; message: string }[] = [];
  const folders = [...new Set(Object.keys(files).map((path) => path.split("/")[0]))];
  for (const folder of folders) {
    const found = FRONT.exec(files[`${folder}/GUIDELINE.md`] ?? "");
    if (!found) { problems.push({ guideline: folder, key: "", message: "must open with a front matter block between two --- lines" }); continue; }
    const meta = Object.fromEntries(found[1].split("\n").map((line) => [line.slice(0, line.indexOf(":")), line.slice(line.indexOf(":") + 1).trim()]));
    for (const key of ["id", "type", "name", "description", "kind", "scope", "severity"]) if (!(key in meta) || meta[key] === '""') problems.push({ guideline: folder, key, message: key === "description" ? "must be non-empty text" : "is required" });
    if (meta.severity && !["error", "warn", "guidance"].includes(JSON.parse(meta.severity))) problems.push({ guideline: folder, key: "severity", message: "must be one of error, warn, guidance" });
    if (meta.name && JSON.parse(meta.name) !== folder) problems.push({ guideline: folder, key: "name", message: `must be the folder's name, ${folder}` });
  }
  return problems;
}

function layer(site: Doc, section: Doc | null): { document: Doc; fieldSources: Record<string, any[]> } {
  const locked = new Set<string>(site.locked ?? []);
  const document: Doc = { ...site };
  const sources: Record<string, any[]> = Object.fromEntries(Object.keys(site).filter((key) => key !== "schemaVersion").map((key) => [key, [{ layer: "publication", version: 1 }]]));
  for (const [key, value] of Object.entries(section ?? {})) {
    if (key === "schemaVersion") continue;
    if (["voice", "audience", "editorialAim", "headline"].includes(key)) {
      if (locked.has(key)) continue;
      document[key] = value; sources[key] = [{ layer: "section", version: 1 }];
    } else if (Array.isArray(value)) {
      document[key] = [...(site[key] ?? []), ...value]; sources[key] = [...(site[key] ? [{ layer: "publication", version: 1 }] : []), { layer: "section", version: 1 }];
    } else if (key === "lexicon") {
      document[key] = { prefer: [...(site.lexicon?.prefer ?? []), ...(value.prefer ?? [])], avoid: [...(site.lexicon?.avoid ?? []), ...(value.avoid ?? [])] };
      sources[key] = [{ layer: "publication", version: 1 }, { layer: "section", version: 1 }];
    }
  }
  return { document, fieldSources: sources };
}

const fileChanges = (before: Files, after: Files) => [
  ...Object.keys(after).filter((path) => !(path in before)).map((path) => ({ path, change: "added" })),
  ...Object.keys(after).filter((path) => path in before && before[path] !== after[path]).map((path) => ({ path, change: "changed" })),
  ...Object.keys(before).filter((path) => !(path in after)).map((path) => ({ path, change: "removed" })),
];

export function createFixtureBackend(scenario: string) {
  const calls: { op: string; input: any }[] = [];
  const store: Record<string, Version[]> = {};
  const seed = (key: string, files: Files, count = 1) => {
    store[key] = Array.from({ length: count }, (_, index) => ({ itemId: `${key}-v${index + 1}`, versionNumber: index + 1, files: index === count - 1 ? files : { ...files, ...filesFromDocument({ tone: [`Draft tone ${index + 1}.`] }, key === "site" ? null : key) }, by: index ? "Sam" : "Ryan", at: iso(index + 1), reason: index ? "Tighten the tone" : "First guidelines" }));
  };
  if (scenario !== "empty") seed("site", filesFromDocument(SITE_DOCUMENT, null, Object.keys(FIXTURE_RULES)), scenario === "history" ? 3 : 1);
  if (scenario === "section") seed("ai", filesFromDocument(SECTION_DOCUMENT, "ai"));
  const current = (key: string) => store[key]?.[store[key].length - 1];
  const keyOf = (input: any) => input.section ?? "site";
  const refused = (problems: { guideline: string; key: string; message: string }[]) => ({ ok: false, error: { code: "invalid_input", message: `The guideline files have problems: ${problems.map((p) => `${p.guideline} ${p.key} ${p.message}`).join("; ")}`, retryable: false, details: { problems } } });

  const door = async (op: string, input: any): Promise<any> => {
    calls.push({ op, input: structuredClone(input) });
    const key = keyOf(input);
    if (op === "guidelines_get") {
      const version = input.version ? store[key]?.find((item) => item.versionNumber === input.version) : current(key);
      if (!version) return { ok: false, error: { code: "not_found", message: "There are no writing guidelines for that yet." } };
      return { ok: true, result: { kind: "writing", document: documentFromFiles(version.files), files: version.files, itemId: version.itemId, versionNumber: version.versionNumber, contentHash: "sha256:x", updatedAt: version.at, updatedBy: version.by, changeReason: version.reason, isCurrent: version === current(key), expectedCurrentVersionId: current(key)!.itemId } };
    }
    if (op === "guidelines_resolve") {
      const site = current("site");
      if (!site) return { ok: true, result: { kind: "writing", found: false, document: {}, fieldSources: {}, layers: [], warnings: [] } };
      return { ok: true, result: { kind: "writing", section: input.section, found: true, ...layer(documentFromFiles(site.files), current(key) ? documentFromFiles(current(key)!.files) : null), layers: [], warnings: [] } };
    }
    if (op === "guidelines_diff") {
      const problems = problemsOf(input.files);
      if (problems.length) return refused(problems);
      const before = current(key)?.files ?? {};
      const [old, now] = [documentFromFiles(before), documentFromFiles(input.files)];
      const changes = Object.keys({ ...old, ...now }).filter((field) => field !== "schemaVersion" && JSON.stringify(old[field]) !== JSON.stringify(now[field])).map((path) => ({ path, from: old[path], to: now[path] }));
      const filesChanged = fileChanges(before, input.files);
      const rules = (files: Files) => new Set(Object.keys(files).map((path) => path.split("/")[0]).filter((name) => !FIELD_FILES.some((field) => field.name === name)));
      const policyPlan = [...rules(input.files)].filter((name) => filesChanged.some((change) => change.path.startsWith(`${name}/`))).map((name) => ({ action: before[`${name}/GUIDELINE.md`] ? "update" : "create", policy: `guideline-${name}`, scope: "publication" }));
      return { ok: true, result: { kind: "writing", changes, fileChanges: filesChanged, policyPlan, constraintChanges: [], wouldCreateVersion: (current(key)?.versionNumber ?? 0) + 1 } };
    }
    if (op === "guidelines_save") {
      if (!String(input.reason ?? "").trim()) return { ok: false, error: { code: "invalid_input", message: "A reason is required." } };
      const expected = current(key)?.itemId ?? "none";
      if (input.expectedCurrentVersionId !== expected) return { ok: false, error: { code: "stale_version", message: "stale" } };
      const problems = problemsOf(input.files);
      if (problems.length) return refused(problems);
      if (JSON.stringify(current(key)?.files) === JSON.stringify(input.files)) return { ok: true, result: { kind: "writing", itemId: expected, versionNumber: current(key)!.versionNumber, contentHash: "sha256:x", unchanged: true } };
      const versionNumber = (current(key)?.versionNumber ?? 0) + 1;
      (store[key] ??= []).push({ itemId: `${key}-v${versionNumber}`, versionNumber, files: input.files, by: "You", at: iso(9), reason: input.reason });
      return { ok: true, result: { kind: "writing", itemId: `${key}-v${versionNumber}`, versionNumber, contentHash: "sha256:y" } };
    }
    if (op === "guidelines_history") {
      const versions = [...(store[key] ?? [])].reverse().map((item) => ({ itemId: item.itemId, versionNumber: item.versionNumber, isCurrent: item === current(key), at: item.at, by: item.by, byKind: "human", reason: item.reason, contentHash: "sha256:x" }));
      return versions.length ? { ok: true, result: { kind: "writing", versions } } : { ok: false, error: { code: "not_found", message: "none" } };
    }
    return { ok: false, error: { code: "invalid_input", message: `Unknown operation ${op}` } };
  };

  const checks = async () => scenario === "empty" ? [] : [
    { id: "c1", title: "Avoid the word leverage", enabled: true, source: "writing-guidelines:editorial-doctrine-writing:v1", policyKey: "avoid-leverage" },
    { id: "c3", title: "Plain claims", enabled: true, source: "writing-guidelines:editorial-doctrine-writing:v1", policyKey: "guideline-plain-claims" },
    { id: "c2", title: "A check an admin wrote", enabled: true, source: "custom", policyKey: "mine" },
  ];
  return { door, calls, stories: async () => STORIES, checks };
}
