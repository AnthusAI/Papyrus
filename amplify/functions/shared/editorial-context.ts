import { createHash } from "node:crypto";
import { tenantScopedValue } from "../../../lib/tenant-keys";

export type EditorialRecord = Record<string, any>;
type Result = { data?: EditorialRecord | EditorialRecord[] | null; errors?: unknown; nextToken?: string | null };
type Model = Record<string, (args: Record<string, any>, options?: Record<string, any>) => Promise<Result>>;
export type EditorialClient = { models: Record<string, Model> };
export type EditorialOptions = {
  publicationKey?: string;
  endpoint: string;
  tenantId?: string;
  sectionId?: string | null;
  storyLineageId?: string | null;
  assignmentId?: string | null;
  maxCharacters?: number | null;
  readAttachment: (attachment: EditorialRecord) => Promise<string>;
};

function checked(response: Result, operation: string) {
  if (response.errors && (!Array.isArray(response.errors) || response.errors.length)) throw new Error(`${operation}: ${JSON.stringify(response.errors)}`);
  return response;
}

async function pages(client: EditorialClient, model: string, index: string, args: EditorialRecord) {
  const rows: EditorialRecord[] = [];
  let nextToken: string | null | undefined;
  do {
    const response = checked(await client.models[model][index](args, { limit: 100, nextToken }), `read ${model} ${index}`);
    rows.push(...(response.data as EditorialRecord[] ?? []));
    nextToken = response.nextToken;
  } while (nextToken);
  return rows;
}

async function get(client: EditorialClient, model: string, id: string) {
  const row = checked(await client.models[model].get({ id }), `read ${model}`).data as EditorialRecord | null;
  if (!row) throw new Error(`${model} not found: ${id}`);
  return row;
}

function tenant(row: EditorialRecord, tenantId?: string) {
  if ((row.tenantId || null) !== (tenantId || null)) throw new Error("Editorial record tenant does not match the configured authoring scope.");
}

function canonical(value: any): any {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}
function digest(value: string) { return createHash("sha256").update(value, "utf8").digest("hex"); }
function entry(scope: string, kind: string, text: string, record: EditorialRecord) {
  return { scope, kind, text, source: {
    ...Object.fromEntries(["id", "lineageId", "versionNumber", "updatedAt", "contentHash"].map(key => [key, record[key] ?? null])),
    sha256: digest(text),
  } };
}

export function buildEditorialContext(publication: EditorialRecord, scope: EditorialRecord, entries: EditorialRecord[], warnings: string[], maxCharacters = 0) {
  const lines = [`Editorial context: ${publication.key}`, "Source: cloud",
    "Precedence: publication > section > assignment. Surface conflicts; narrower instructions do not silently override publication policy.",
    "Private operating guidance; not evidence or reader-facing copy."];
  for (const value of entries) lines.push("", `## ${value.scope}: ${value.kind}`, value.text);
  const text = lines.join("\n") + "\n";
  const totalCharacters = Array.from(text).length;
  if (!Number.isInteger(maxCharacters) || maxCharacters < 0) throw new Error("Editorial context budget must be nonnegative.");
  if (maxCharacters && totalCharacters > maxCharacters) throw new Error(`Editorial context budget ${maxCharacters} cannot hold ${totalCharacters} required characters; policy was not truncated.`);
  const payload = { schemaVersion: 1, rendererVersion: "editorial-context/v1", publication, scope, sourceMode: "cloud",
    precedence: ["publication", "section", "assignment"], entries, sources: entries.map(value => value.source), warnings, text, totalCharacters };
  return { ...payload, contextHash: digest(JSON.stringify(canonical(payload))), resolvedAt: new Date().toISOString() };
}

/** Private source adapter for the same deterministic contract exposed by papyrus editorial context. */
export async function resolveEditorialContext(client: EditorialClient, options: EditorialOptions) {
  if (!options.endpoint) throw new Error("Explicit publication endpoint is required for hosted editorial context.");
  const corpora = await pages(client, "KnowledgeCorpus", "listKnowledgeCorporaByRoleAndName", { role: "canonical" });
  const requested = options.publicationKey;
  const normalized = requested?.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 140);
  if (corpora.length !== 1 || !corpora[0].id?.startsWith("knowledge-corpus-") || corpora[0].role !== "canonical" || !corpora[0].name?.trim() ||
      (requested !== undefined && (!normalized || corpora[0].id !== `knowledge-corpus-${normalized}`))) {
    throw new Error("Requested publication does not match the hosted canonical corpus; missing or ambiguous publication binding.");
  }
  const publication = { key: corpora[0].id.slice("knowledge-corpus-".length), name: corpora[0].name,
    corpusId: corpora[0].id, tenantId: options.tenantId ?? null, endpoint: options.endpoint };
  const entries: EditorialRecord[] = [];
  const warnings: string[] = [];
  let sectionId = options.sectionId || null;
  let storyLineageId = options.storyLineageId || null;
  const assignmentId = options.assignmentId || null;
  let assignment: EditorialRecord | undefined;
  if (assignmentId) {
    assignment = await get(client, "Assignment", assignmentId);
    const assignedStory = assignment.itemLineageId;
    if (storyLineageId && assignedStory && storyLineageId !== assignedStory) throw new Error("Requested story conflicts with assignment story lineage.");
    storyLineageId ||= assignedStory || null;
    const assignedSection = assignment.sectionKey || assignment.sectionId;
    if (sectionId && assignedSection && sectionId !== assignedSection) throw new Error("Requested section conflicts with assignment section.");
    sectionId ||= assignedSection || null;
    warnings.push("Assignment policy snapshots are ignored; current publication and section records govern. Surface any conflicting assignment instructions.");
  }
  if (storyLineageId) {
    const versions = await pages(client, "Item", "listItemsByLineageAndVersion", { lineageId: storyLineageId });
    if (!versions.length) throw new Error(`Story not found: ${storyLineageId}`);
    const story = versions.reduce((a, b) => Number(b.versionNumber || 0) > Number(a.versionNumber || 0) ? b : a);
    tenant(story, options.tenantId);
    if (sectionId && story.section && sectionId !== story.section) throw new Error("Requested section conflicts with story section.");
    sectionId ||= story.section || null;
  }
  for (const kind of ["mission", "policy"]) {
    const slug = `editorial-doctrine-${kind}`;
    const rows = await pages(client, "Item", options.tenantId ? "itemByTenantSlug" : "itemBySlug",
      options.tenantId ? { tenantSlug: tenantScopedValue(options.tenantId, slug) } : { slug });
    const current = rows.filter(row => row.type === "doctrine" && row.status === "private" && row.versionState === "current");
    if (current.length !== 1) throw new Error(`Publication ${kind}: expected exactly one current record, found ${current.length}.`);
    const record = current[0];
    tenant(record, options.tenantId);
    const text = record.bodyMarkus ? String(record.bodyMarkus).trim() : (record.body ?? []).map((part: any) => String(part).trim()).filter(Boolean).join("\n\n");
    if (!text) throw new Error(`Required publication ${kind} is empty.`);
    entries.push(entry("publication", kind, text, record));
  }
  if (sectionId) {
    const section = await get(client, "NewsroomSection", sectionId);
    tenant(section, options.tenantId);
    for (const [kind, key] of [["mission", "editorialMission"], ["policy", "editorialPolicy"], ["guidance", "assignmentGuidance"], ["kill criteria", "killCriteria"]]) {
      const text = String(section[key] || "").trim();
      if (text) entries.push(entry("section", kind, text, section));
      else if (kind === "mission" || kind === "policy") warnings.push(`Section ${section.id} intentionally has an empty ${kind} slot; publication doctrine still applies.`);
    }
  }
  if (assignment) {
    if (options.tenantId && !storyLineageId && !sectionId) throw new Error("A tenant assignment needs a scoped story or section to establish its publication.");
    const attachments = await pages(client, "ModelAttachment", "listModelAttachmentsByOwnerRoleAndSortKey", { ownerId: assignment.id });
    let foundBrief = false;
    for (const [role, kind] of [["assignment_brief", "brief"], ["assignment_instructions", "instructions"]]) {
      const matching = attachments.filter(row => row.role === role && row.status !== "deleted");
      if (matching.length > 1) throw new Error(`Ambiguous assignment ${kind} attachments.`);
      if (matching.length) {
        const attachment = matching[0];
        if (attachment.ownerKind !== "assignment" || attachment.ownerId !== assignment.id) throw new Error("Assignment attachment owner does not match the requested scope.");
        const text = (await options.readAttachment(attachment)).trim();
        if (!text) throw new Error(`Assignment ${kind} attachment is empty.`);
        entries.push(entry("assignment", kind, text, attachment));
        foundBrief ||= kind === "brief";
      }
    }
    if (!foundBrief && assignment.summary) {
      entries.push(entry("assignment", "brief", assignment.summary, assignment));
      warnings.push("No assignment brief attachment exists; the Assignment summary is supplied as its brief.");
    }
  }
  return buildEditorialContext(publication, { sectionId, storyLineageId, assignmentId }, entries, warnings, options.maxCharacters ?? 0);
}

export function assignmentDoctrine(pack: Awaited<ReturnType<typeof resolveEditorialContext>>) {
  return pack.entries.filter(value => value.scope !== "assignment").map(value => ({
    scope: value.scope === "section" ? "desk" : "publication", kind: value.kind,
    label: `${value.scope === "section" ? "Section" : "Editorial"} ${value.kind}`,
    slug: value.scope === "section" ? `desk-section-${pack.scope.sectionId}-${value.kind.replaceAll(" ", "-")}` : `editorial-doctrine-${value.kind}`,
    body: [value.text], ...(value.scope === "section" ? { categoryKey: pack.scope.sectionId, categoryLineageId: pack.scope.sectionId } : {}),
  }));
}
