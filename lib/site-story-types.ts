import { SYSTEM_ITEM_TYPES, UNTYPED_ITEM_TYPE } from "./content-item-lifecycle";

/**
 * The Story types a site offers, read from the site's own projection.json (the file the projector reads; `storyTypes` and `urls`).
 * `withPapyrus` copies the few settings this needs into NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES at build time; `src/papyrus_content/story_types.py` reads the same file on
 * the Python side. Both derive `default` and `types` the same way, and scripts/fixtures/story-types-cases.json holds the cases each language's tests run.
 *
 *   "storyTypes": { "default": "article", "types": ["article", "post"] }     (both keys optional)
 *
 * With no default a new Story has no type until an editor picks one (it is stored as "untyped" and cannot be published). With no `types` the offered types
 * are the default, when there is one, plus every type in `urls.types`.
 */
export const PROJECTION_TYPES_ENV = "NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES";
const TYPE_NAME = /^[a-z][a-z0-9_]*$/;
/** The Item types every standard projection builds pages for, before the site's `listings.types` and `urls.types`. Mirrors EXPORTED_TYPES in markus_export.py for the Story-relevant ones. */
export const ALWAYS_PROJECTED = ["article", "page"];

export type SiteStoryTypes = {
  /** The type a new Story gets; null when the site names none (the Story then has no type until an editor chooses one). */
  default: string | null;
  /** The types an editor can choose, in the site's order. */
  types: string[];
  /** The public base (a path segment, "" for the site root) of each type that has a `urls.types` entry. */
  typeBases: Record<string, string>;
  /** The public base of each declared section (aliases included). A declared section decides the address before the type does. */
  sectionBases: Record<string, string>;
  /** The Item types the projection builds pages for. */
  projected: string[];
  /** The site declares URL groups, so an Item in an undeclared section has no page. */
  sectioned: boolean;
};

type Raw = Record<string, unknown>;
const record = (value: unknown): Raw => (value && typeof value === "object" && !Array.isArray(value) ? (value as Raw) : {});

function requireStoryType(value: unknown, where: string): string {
  const name = typeof value === "string" ? value : "";
  if (!TYPE_NAME.test(name)) throw new Error(`${where} is a lowercase name such as 'article' or 'guide', not ${JSON.stringify(value)}.`);
  if (name === UNTYPED_ITEM_TYPE) throw new Error(`${where} cannot be '${name}': that is the value of a Story with no type yet, not a type to choose.`);
  if (SYSTEM_ITEM_TYPES.includes(name)) throw new Error(`${where} cannot be '${name}': that type is not a Story.`);
  return name;
}

/** The Story types of a projection.json mapping (the whole file, or the slice `withPapyrus` copies). Throws on an invalid declaration. */
export function storyTypesFromProjection(projection: unknown): SiteStoryTypes {
  const raw = record(projection);
  const declared = record(raw.storyTypes);
  const unknown = Object.keys(declared).filter(key => key !== "default" && key !== "types");
  if (unknown.length) throw new Error(`Unknown storyTypes settings: ${unknown.sort().join(", ")}`);
  const defaultType = declared.default === undefined || declared.default === null ? null : requireStoryType(declared.default, "storyTypes.default");
  const urls = record(raw.urls);
  const urlTypes = record(urls.types);
  const urlSections = record(urls.sections);
  let types: string[];
  if (Array.isArray(declared.types)) {
    types = [...new Set(declared.types.map(name => requireStoryType(name, "storyTypes.types entries")))];
    if (defaultType !== null && !types.includes(defaultType)) throw new Error(`storyTypes.default '${defaultType}' is not one of storyTypes.types (${types.join(", ")}).`);
  } else {
    types = [...new Set([...(defaultType === null ? [] : [defaultType]), ...Object.keys(urlTypes).filter(name => !SYSTEM_ITEM_TYPES.includes(name))])];
  }
  const typeBases: Record<string, string> = {};
  for (const [name, entry] of Object.entries(urlTypes)) typeBases[name] = String(record(entry).base ?? name);
  const sectionBases: Record<string, string> = {};
  for (const [name, entry] of Object.entries(urlSections)) {
    const base = String(record(entry).base ?? name);
    sectionBases[name] = base;
    const aliases = record(entry).aliases;
    if (Array.isArray(aliases)) for (const alias of aliases) sectionBases[String(alias)] = base;
  }
  const listed = Array.isArray(record(raw.listings).types) ? (record(raw.listings).types as unknown[]).map(String) : ["article"];
  return {
    default: defaultType,
    types,
    typeBases,
    sectionBases,
    projected: [...new Set([...ALWAYS_PROJECTED, ...listed, ...Object.keys(urlTypes)])],
    sectioned: Object.keys(urlTypes).length + Object.keys(urlSections).length > 0,
  };
}

let cached: SiteStoryTypes | null = null;

/** The running site's Story types. Without the build-time slice (the engine's own preview, a site that declares nothing) there are none and no default. */
export function siteStoryTypes(environment: Record<string, string | undefined> = process.env): SiteStoryTypes {
  if (environment === process.env && cached) return cached;
  let found: SiteStoryTypes;
  try {
    // Next inlines only a literal `process.env.NEXT_PUBLIC_*` access in browser code, so the default read names the variable.
    const text = environment === process.env ? process.env.NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES : environment[PROJECTION_TYPES_ENV];
    found = storyTypesFromProjection(text ? JSON.parse(text) : {});
  } catch (error) {
    console.warn(`The site's Story types are invalid; offering none: ${error instanceof Error ? error.message : String(error)}`);
    found = storyTypesFromProjection({});
  }
  if (environment === process.env) cached = found;
  return found;
}

/** The type a new Story is stored with: the site's default, else "untyped". */
export function typeForNewStory(types: SiteStoryTypes = siteStoryTypes()): string {
  return types.default ?? UNTYPED_ITEM_TYPE;
}

export type StoryAddress =
  | { kind: "route"; base: string; via: "type" | "section" | "root" }
  | { kind: "none"; reason: string };

/**
 * Where a Story of this type and section is published, as far as the site's settings say (the projector decides at publish and reports what it did).
 * A declared section wins over the type; otherwise the type's `urls.types` entry; otherwise a Story with no section is a page of the site root when its type is
 * projected at all; a Story whose section the site does not declare, or whose type the projection does not build, has no public page.
 */
export function storyAddress(types: SiteStoryTypes, type: string, section: string | null | undefined): StoryAddress {
  const topic = (section ?? "").trim();
  if (topic && topic in types.sectionBases) return { kind: "route", base: types.sectionBases[topic], via: "section" };
  if (type in types.typeBases) return { kind: "route", base: types.typeBases[type], via: "type" };
  if (!types.projected.includes(type)) {
    return { kind: "none", reason: `This site has no page for the type "${type}": it is not in the site's urls.types or listings.types.` };
  }
  if (types.sectioned && topic) return { kind: "none", reason: `This site declares no address for the section "${topic}" and none for the type "${type}".` };
  return { kind: "route", base: "", via: "root" };
}

/** `/articles/` for a base of `articles`; `the site root` for "". */
export function describeBase(base: string): string {
  return base ? `/${base}/` : "the site root";
}
