/**
 * Guideline files in the console (PPY-b0c478): the writing guidelines are a set of files, `<name>/GUIDELINE.md`, each with flat front matter and a prose body
 * (`src/papyrus_content/guidelines/files.py`, `field_files.py`). This module reads a set into the folders the editor shows, makes the text of a changed file, and
 * names what each file does (its severity, the check it derives). It never decides whether a set is valid: the guidelines door refuses a set with problems and
 * names each one by file and key (`guidelines_diff` and `guidelines_save`), and the editor shows those.
 */
import type { GuidelineDocument } from "./writing-guidelines-admin";

export const FILE_NAME = "GUIDELINE.md";
export const TYPE = "papyrus:Guideline";
export const SEVERITIES = ["error", "warn", "guidance"] as const;
export type Severity = (typeof SEVERITIES)[number];
export const LIST_KEYS = ["avoid", "prefer", "pattern"] as const;
export const KEY_ORDER = ["id", "type", "name", "description", "kind", "scope", "severity", "language", "avoid", "prefer", "pattern", "maxLength"] as const;
export const SEVERITY_WORDS: Record<Severity, string> = { error: "Error", warn: "Warning", guidance: "Guidance" };
export const SEVERITY_HINTS: Record<Severity, string> = {
  error: "A writer must fix it. It derives an editorial check that blocks.",
  warn: "A writer should look at it. It derives an editorial check that warns.",
  guidance: "Read by writers and agents. It derives no check.",
};

export type Scalar = string | number | boolean | null;
export type Meta = Record<string, Scalar | Scalar[]>;
export type FieldForm = "text" | "bullets" | "json";
export type FieldFile = { key: string; name: string; label: string; form: FieldForm; template: string };

const kebab = (key: string) => key.replace(/(?<!^)(?=[A-Z])/g, "-").toLowerCase();
const field = (key: string, label: string, form: FieldForm, template = ""): FieldFile => ({ key, name: kebab(key), label, form, template });
const OBJECT = "{}", LIST = "[]";

/** Every field file the writing guidelines know (the fixed names of `field_files.FORMS`), with what a new one starts with. */
export const FIELD_FILES: FieldFile[] = [
  field("voice", "Voice", "json", '{\n  "name": ""\n}'), field("audience", "Audience", "text"), field("headline", "Headline", "json", OBJECT), field("editorialAim", "Editorial aim", "text"),
  field("register", "Register", "text"), field("tone", "Tone", "bullets"), field("sentenceStyle", "Sentence style", "bullets"), field("voicePatterns", "Voice patterns", "bullets"),
  field("structure", "Structure", "bullets"), field("evidenceRules", "Evidence rules", "bullets"), field("bodyMarkus", "Guidance in your own words", "text"),
  field("lexicon", "Words to prefer and avoid", "json", '{\n  "prefer": [],\n  "avoid": []\n}'), field("glossary", "Glossary", "json", LIST), field("exemplars", "Voice examples", "json", LIST),
  field("constraints", "Binding rules", "json", LIST), field("publicationKey", "Publication key", "text"), field("judge", "Judge", "json", OBJECT), field("checks", "Checks", "json", OBJECT),
  field("density", "Density", "json", OBJECT), field("rules", "Rules", "json", OBJECT), field("compare", "Compare", "json", OBJECT), field("referenceSamples", "Reference samples", "json", LIST),
  field("locked", "Fields a section may not replace", "bullets"),
];
const BY_NAME = new Map(FIELD_FILES.map((item) => [item.name, item]));
export const fieldFileNamed = (name: string): FieldFile | undefined => BY_NAME.get(name);

/** A section's set holds additions only: these belong to the publication (or to a language overlay) and are never offered on a section tab. */
const PUBLICATION_OR_LANGUAGE_ONLY = new Set(["locked", "constraints", "publicationKey", "judge", "checks", "density", "rules", "compare", "referenceSamples", "register"]);
/** The field files a person can still add here (`register` is a language overlay's field, so it is never offered). */
export const addableFieldFiles = (present: Set<string>, section: string | null, lockedKeys: string[]): FieldFile[] =>
  FIELD_FILES.filter((item) => !present.has(item.name) && item.key !== "register" && !(section !== null && (PUBLICATION_OR_LANGUAGE_ONLY.has(item.key) || lockedKeys.includes(item.key))));

// --- front matter ----------------------------------------------------------------------------------------------------------------------------------

/** The flat front matter subset of `front_matter.py`: `key: value` lines; text plain or quoted, a number, true, false, null, or a flat list inline or as `- item` lines. */
function scalar(raw: string): Scalar {
  const text = raw.replace(/\s#.*$/, "").trim();
  if (text === "" || text === "~" || /^null$/i.test(text)) return null;
  if (/^true$/i.test(text)) return true;
  if (/^false$/i.test(text)) return false;
  if (/^-?\d+$/.test(text)) return Number(text);
  if (/^-?\d+\.\d+$/.test(text)) return Number(text);
  if (text.startsWith('"')) { const parsed = JSON.parse(text); if (typeof parsed !== "string") throw new Error("a quoted text is not valid"); return parsed; }
  if (text.startsWith("'")) { if (!text.endsWith("'") || text.length < 2) throw new Error("a single-quoted text is not closed"); return text.slice(1, -1).replace(/''/g, "'"); }
  return text;
}

function splitFlow(inner: string): string[] {
  const items: string[] = []; let current = "", quote = "";
  for (let index = 0; index < inner.length; index += 1) {
    const char = inner[index];
    if (quote) { current += char; if (char === "\\" && quote === '"') { current += inner[index += 1] ?? ""; } else if (char === quote) quote = ""; }
    else if (char === '"' || char === "'") { quote = char; current += char; }
    else if (char === ",") { items.push(current); current = ""; }
    else current += char;
  }
  if (current.trim() || items.length) items.push(current);
  return items.filter((item, at) => item.trim() !== "" || at < items.length - 1);
}

export function parseFrontMatter(lines: string): Meta {
  const meta: Meta = {};
  const rows = lines.replace(/\r\n/g, "\n").split("\n");
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row.trim() || row.trimStart().startsWith("#")) continue;
    const found = /^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]+(.*))?$/.exec(row);
    if (!found) throw new Error(`a line is not 'key: value': ${row.trim().slice(0, 60)}`);
    const [, key, rest = ""] = found;
    if (key in meta) throw new Error(`the key ${key} is there twice`);
    const value = rest.trim();
    if (value === "" || value.startsWith("#")) {
      const items: Scalar[] = [];
      while (index + 1 < rows.length && (!rows[index + 1].trim() || /^[ \t]*-([ \t]|$)/.test(rows[index + 1]))) {
        index += 1;
        if (rows[index].trim()) items.push(scalar(rows[index].trim().slice(1)));
      }
      meta[key] = items.length ? items : null;
    } else if (value.startsWith("[")) {
      const body = value.replace(/\s#.*$/, "").trim();
      if (!body.endsWith("]")) throw new Error("a list is not closed");
      meta[key] = splitFlow(body.slice(1, -1)).map(scalar);
    } else if (value.startsWith("{")) throw new Error(`${key} is nested; the front matter is flat`);
    else meta[key] = scalar(value);
  }
  return meta;
}

const dumpScalar = (value: Scalar): string => (typeof value === "string" ? JSON.stringify(value) : value === null ? "null" : String(value));

/** The front matter lines of a flat mapping, the way `front_matter.dumps` writes them: texts always double-quoted, lists inline. */
export function dumpFrontMatter(meta: Meta): string {
  return Object.entries(meta).map(([key, value]) => `${key}: ${Array.isArray(value) ? `[${value.map(dumpScalar).join(", ")}]` : dumpScalar(value)}`).join("\n") + "\n";
}

export const fileText = (meta: Meta, body: string): string => `---\n${dumpFrontMatter(meta)}---\n${body}`;

const FRONT = /^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)([\s\S]*)$/;

// --- a set as folders ------------------------------------------------------------------------------------------------------------------------------

export type Folder = {
  folder: string;
  /** "field": a fixed name, one field of the house style. "rule": any other name, a guideline with a severity. */
  role: "field" | "rule";
  text: string;
  meta: Meta;
  body: string;
  /** The files beside GUIDELINE.md (supporting files): kept as they are, and removed with the folder. */
  extras: string[];
  /** Why the front matter cannot be read here; the door names what is wrong with the file when it is saved. */
  unreadable: string | null;
};

export const pathOf = (folder: string): string => `${folder}/${FILE_NAME}`;
const folderOf = (path: string): string => path.split("/")[0];

export function foldersOf(files: Record<string, string>): Folder[] {
  const names = [...new Set(Object.keys(files).filter((path) => path.includes("/")).map(folderOf))].sort();
  return names.map((folder) => {
    const text = files[pathOf(folder)] ?? "";
    const extras = Object.keys(files).filter((path) => folderOf(path) === folder && path !== pathOf(folder)).sort();
    const found = FRONT.exec(text.replace(/\r\n/g, "\n"));
    let meta: Meta = {}, body = "", unreadable: string | null = null;
    if (!found) unreadable = text ? "It does not open with a front matter block between two --- lines." : `It has no ${FILE_NAME}.`;
    else { try { meta = parseFrontMatter(found[1]); body = found[2]; } catch (error) { unreadable = error instanceof Error ? error.message : "The front matter cannot be read."; } }
    return { folder, role: BY_NAME.has(folder) ? "field" : "rule", text, meta, body, extras, unreadable };
  });
}

export const severityOf = (item: Folder): Severity => (SEVERITIES as readonly string[]).includes(item.meta.severity as string) ? (item.meta.severity as Severity) : "guidance";
export const textOf = (item: Folder, key: string): string => (typeof item.meta[key] === "string" ? (item.meta[key] as string) : "");
export const linesOf = (item: Folder, key: string): string[] => (Array.isArray(item.meta[key]) ? (item.meta[key] as Scalar[]).map(String) : []);
export const maxLengthOf = (item: Folder): string => (item.meta.maxLength == null ? "" : String(item.meta.maxLength));
export const lines = (text: string): string[] => text.split("\n").map((line) => line.trim()).filter(Boolean);

/** What a rule file can decide with no model: a listed word, a pattern, a length. Prose alone needs judgement. */
export const isDecidable = (item: Folder): boolean => linesOf(item, "avoid").length + linesOf(item, "pattern").length > 0 || item.meta.maxLength != null;
/** What derives a check (`derived_policies.rule_policy`): an `error` or `warn` rule file, named `guideline-<name>`. */
export const derivesCheck = (item: Folder): boolean => item.role === "rule" && severityOf(item) !== "guidance";
export const checkKey = (item: Folder): string => `guideline-${item.folder}`;

/** The text of a file after one front matter key is set. A key given no value is dropped. Key order is kept; a new key goes where the file form puts it. */
export function withMeta(item: Folder, patch: Record<string, Scalar | Scalar[] | undefined>): string {
  const meta: Meta = { ...item.meta };
  for (const [key, value] of Object.entries(patch)) { if (value === undefined || (Array.isArray(value) && value.length === 0)) delete meta[key]; else meta[key] = value; }
  const known = KEY_ORDER.filter((key) => key in meta), rest = Object.keys(meta).filter((key) => !(KEY_ORDER as readonly string[]).includes(key));
  return fileText(Object.fromEntries([...known, ...rest].map((key) => [key, meta[key]])), item.body);
}
export const withBody = (item: Folder, body: string): string => (item.unreadable ? item.text : fileText(item.meta, body));

// --- adding a file ---------------------------------------------------------------------------------------------------------------------------------

export const lineageScope = (section: string | null): string => (section ? `section/${section.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "topic"}` : "publication");
const NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
/** A random version 4 UUID from `getRandomValues`, which a page served over plain http (a LAN preview) still has; `randomUUID` needs a secure origin. */
export function newId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `urn:uuid:${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function newRuleName(name: string, existing: string[]): string | null {
  const word = name.trim();
  if (!word) return "Give the rule a name.";
  if (!NAME.test(word)) return "A name is lowercase words joined by hyphens, such as plain-claims.";
  if (BY_NAME.has(word)) return `${word} is the name of a field file. Add it as a field file, or choose another name.`;
  if (existing.includes(word)) return `There is already a file named ${word}.`;
  return null;
}

export function newRuleFile(name: string, section: string | null): string {
  return fileText({ id: newId(), type: TYPE, name, description: "", kind: "writing", scope: lineageScope(section), severity: "guidance" }, "");
}

export function newFieldFile(item: FieldFile, section: string | null): string {
  const body = item.form === "json" ? `\`\`\`json\n${item.template}\n\`\`\`\n` : item.form === "bullets" ? "- \n" : "\n";
  return fileText({ id: newId(), type: TYPE, name: item.name, description: `${item.label} in the writing guidelines.`, kind: "writing", scope: lineageScope(section), severity: "guidance" }, body);
}

// --- what changed since the saved set --------------------------------------------------------------------------------------------------------------

export type FileState = "unchanged" | "changed" | "added" | "removed";
export const STATE_WORDS: Record<FileState, string> = { unchanged: "Unchanged", changed: "Changed", added: "Added", removed: "Removed" };

export function stateOf(folder: string, saved: Record<string, string>, draft: Record<string, string>): FileState {
  const was = Object.keys(saved).filter((path) => folderOf(path) === folder), now = Object.keys(draft).filter((path) => folderOf(path) === folder);
  if (!was.length) return now.length ? "added" : "unchanged";
  if (!now.length) return "removed";
  return was.length === now.length && was.every((path) => saved[path] === draft[path]) ? "unchanged" : "changed";
}

/** Every folder of either set, in name order, with whether it changed. A removed folder is listed so it can be put back. */
export function folderNames(saved: Record<string, string>, draft: Record<string, string>): string[] {
  return [...new Set([...Object.keys(saved), ...Object.keys(draft)].filter((path) => path.includes("/")).map(folderOf))].sort();
}

export const withoutFolder = (files: Record<string, string>, folder: string): Record<string, string> => Object.fromEntries(Object.entries(files).filter(([path]) => folderOf(path) !== folder));
/** The set with one folder as `from` has it (put back as saved), or without it when `from` has none. */
export const restoreFolder = (draft: Record<string, string>, saved: Record<string, string>, folder: string): Record<string, string> =>
  ({ ...withoutFolder(draft, folder), ...Object.fromEntries(Object.entries(saved).filter(([path]) => folderOf(path) === folder)) });
export const changedCount = (saved: Record<string, string>, draft: Record<string, string>): number => folderNames(saved, draft).filter((folder) => stateOf(folder, saved, draft) !== "unchanged").length;

/** The set the door answered with, as text by path (a value that is not text is left out, so a malformed answer shows as an empty set, never a crash). */
export const filesFrom = (value: Record<string, unknown> | undefined): Record<string, string> =>
  Object.fromEntries(Object.entries(value ?? {}).filter((entry): entry is [string, string] => typeof entry[1] === "string"));

/** The fields locked by the site, read from the site's document view. */
export const lockedKeys = (siteDocument: GuidelineDocument | null): string[] => (Array.isArray(siteDocument?.locked) ? siteDocument!.locked.filter((item: unknown) => typeof item === "string") : []);

// --- the Story picker's example list ---------------------------------------------------------------------------------------------------------------

const JSON_BLOCK = /^```json\n([\s\S]*)\n```\n?$/;
export type Exemplar = { storyLineageId: string; note?: string };

/** The voice examples a `exemplars` file body holds, or null when the body is not the fenced list. */
export function exemplarsOf(body: string): Exemplar[] | null {
  const found = JSON_BLOCK.exec(body.replace(/\r\n/g, "\n"));
  if (!found) return null;
  try { const value = JSON.parse(found[1]); return Array.isArray(value) ? value : null; } catch { return null; }
}
export const exemplarsBody = (items: Exemplar[]): string => `\`\`\`json\n${JSON.stringify(items, null, 2)}\n\`\`\`\n`;

/** The items of a bullets body (`- item` lines; a longer sentence continues on lines indented by two spaces). */
export const bulletsOf = (body: string): string[] => body.replace(/\r\n/g, "\n").split("\n").filter((line) => line.startsWith("- ")).map((line) => line.slice(2).trim()).filter(Boolean);

/** The fields the site locks, read from the site's own `locked` file (the Site tab edits it, so it shows what the draft says). */
export const lockedInFiles = (files: Record<string, string>): string[] => {
  const found = foldersOf(files).find((item) => item.folder === "locked");
  return found && !found.unreadable ? bulletsOf(found.body) : [];
};

/** What differs between two versions in the rule files (the field files are compared as the document they make). */
export function ruleFileChanges(older: Record<string, string>, newer: Record<string, string>): { folder: string; change: "added" | "changed" | "removed" }[] {
  return folderNames(older, newer).filter((folder) => !BY_NAME.has(folder)).flatMap((folder) => {
    const state = stateOf(folder, older, newer);
    return state === "unchanged" ? [] : [{ folder, change: state }];
  });
}
