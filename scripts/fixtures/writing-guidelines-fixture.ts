/**
 * An in-browser stand-in for the guidelines door, for the Writing guidelines page's browser test only: guidelines_get, resolve, diff, save and history for the
 * writing kind, kept in memory, with the same layering rule the real resolver uses for the fields the fixture has (prose adds, choices win unless locked).
 * It reads and writes nothing outside the page.
 */
type Doc = Record<string, any>;
type Version = { itemId: string; versionNumber: number; document: Doc; by: string; at: string; reason: string };

export const SITE_DOCUMENT: Doc = {
  schemaVersion: 1,
  voice: { name: "Plain newsroom" },
  audience: "Readers who build and run AI systems at work.",
  editorialAim: "Explain what changed and why it matters, with evidence.",
  tone: ["Plain and specific.", "Calm, never breathless."],
  sentenceStyle: ["Short sentences. One idea each."],
  lexicon: { prefer: ["people"], avoid: ["leverage", "game-changing"] },
  glossary: [{ term: "Papyrus", use: "Papyrus", avoid: ["the CMS"] }],
  bodyMarkus: "Lead with the news. Name the source in the first paragraph.",
  locked: ["audience"],
  constraints: [{ id: "no-hype", text: "Never describe a product as revolutionary." }],
};
const SECTION_DOCUMENT: Doc = { schemaVersion: 1, tone: ["Warmer in the Culture section."], lexicon: { avoid: ["synergy"] } };

export const SECTIONS = [{ key: "ai", name: "AI" }, { key: "culture", name: "Culture" }];
export const STORIES = [
  { lineageId: "story-1", title: "How the newsroom checks a claim" }, { lineageId: "story-2", title: "A week of agent mistakes" },
  { lineageId: "story-3", title: "What a good headline does" },
];

const iso = (day: number) => `2026-11-0${day}T12:00:00.000Z`;

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

export function createFixtureBackend(scenario: string) {
  const calls: { op: string; input: any }[] = [];
  const store: Record<string, Version[]> = {};
  const seed = (key: string, document: Doc, count = 1) => {
    store[key] = Array.from({ length: count }, (_, index) => ({ itemId: `${key}-v${index + 1}`, versionNumber: index + 1, document: index === count - 1 ? document : { ...document, tone: [`Draft tone ${index + 1}.`] }, by: index ? "Sam" : "Ryan", at: iso(index + 1), reason: index ? "Tighten the tone" : "First guidelines" }));
  };
  if (scenario !== "empty") seed("site", SITE_DOCUMENT, scenario === "history" ? 3 : 1);
  if (scenario === "section") seed("ai", SECTION_DOCUMENT);
  const current = (key: string) => store[key]?.[store[key].length - 1];
  const keyOf = (input: any) => input.section ?? "site";

  const door = async (op: string, input: any): Promise<any> => {
    calls.push({ op, input: structuredClone(input) });
    const key = keyOf(input);
    if (op === "guidelines_get") {
      const version = input.version ? store[key]?.find((item) => item.versionNumber === input.version) : current(key);
      if (!version) return { ok: false, error: { code: "not_found", message: "There are no writing guidelines for that yet." } };
      return { ok: true, result: { kind: "writing", document: version.document, itemId: version.itemId, versionNumber: version.versionNumber, contentHash: "sha256:x", updatedAt: version.at, updatedBy: version.by, changeReason: version.reason, isCurrent: version === current(key), expectedCurrentVersionId: current(key)!.itemId } };
    }
    if (op === "guidelines_resolve") {
      const site = current("site");
      if (!site) return { ok: true, result: { kind: "writing", found: false, document: {}, fieldSources: {}, layers: [], warnings: [] } };
      return { ok: true, result: { kind: "writing", section: input.section, found: true, ...layer(site.document, current(key)?.document ?? null), layers: [], warnings: [] } };
    }
    if (op === "guidelines_diff") {
      const before = current(key)?.document ?? {};
      const changes = Object.keys({ ...before, ...input.document }).filter((field) => field !== "schemaVersion" && JSON.stringify(before[field]) !== JSON.stringify(input.document[field])).map((path) => ({ path, from: before[path], to: input.document[path] }));
      return { ok: true, result: { kind: "writing", changes, constraintChanges: [], wouldCreateVersion: (current(key)?.versionNumber ?? 0) + 1 } };
    }
    if (op === "guidelines_save") {
      if (!String(input.reason ?? "").trim()) return { ok: false, error: { code: "invalid_input", message: "A reason is required." } };
      const expected = current(key)?.itemId ?? "none";
      if (input.expectedCurrentVersionId !== expected) return { ok: false, error: { code: "stale_version", message: "stale" } };
      if (JSON.stringify(current(key)?.document) === JSON.stringify(input.document)) return { ok: true, result: { kind: "writing", itemId: expected, versionNumber: current(key)!.versionNumber, contentHash: "sha256:x", unchanged: true } };
      const versionNumber = (current(key)?.versionNumber ?? 0) + 1;
      (store[key] ??= []).push({ itemId: `${key}-v${versionNumber}`, versionNumber, document: input.document, by: "You", at: iso(9), reason: input.reason });
      return { ok: true, result: { kind: "writing", itemId: `${key}-v${versionNumber}`, versionNumber, contentHash: "sha256:y" } };
    }
    if (op === "guidelines_history") {
      const versions = [...(store[key] ?? [])].reverse().map((item) => ({ itemId: item.itemId, versionNumber: item.versionNumber, isCurrent: item === current(key), at: item.at, by: item.by, byKind: "human", reason: item.reason, contentHash: "sha256:x" }));
      return versions.length ? { ok: true, result: { kind: "writing", versions } } : { ok: false, error: { code: "not_found", message: "none" } };
    }
    return { ok: false, error: { code: "invalid_input", message: `Unknown operation ${op}` } };
  };

  const checks = async () => scenario === "empty" ? [] : [
    { id: "c1", title: "Avoid the word leverage", enabled: true, source: "writing-guidelines:editorial-doctrine-writing:v1" },
    { id: "c2", title: "A check an admin wrote", enabled: true, source: "custom" },
  ];
  return { door, calls, stories: async () => STORIES, checks };
}
