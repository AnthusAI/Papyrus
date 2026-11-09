/**
 * Changes the role of a source attached to a Story (consulted, cited, based on), and nothing else.
 *
 * `SemanticRelation` is append-only for the editor and administrator groups: their tokens may read and create rows but never update one, so a
 * category note or a provenance record cannot be rewritten from a browser or a signed-in CLI. A Story's source is the one relation an editor must
 * change after it exists (attached as "consulted" while reporting, "cited" once the draft quotes it). This route makes that one change on the
 * editor's behalf: it refuses any row that is not a Story-to-Reference `uses_evidence` link, and writes only the role, the citation key, the note
 * and who changed it. The Python writer is `link_reference_to_story` in src/papyrus_content/story_reporting.py; the two must agree on these names.
 */

import { hasEditorRights } from "../../../lib/staff-groups";

export const STORY_REFERENCE_PREDICATE = "uses_evidence";
export const STORY_REFERENCE_KIND = "story.reference";
export const BASED_ON = "based_on";
export const STORY_REFERENCE_ROLES: readonly string[] = ["consulted", "cited", BASED_ON];
const MAXIMUM_CITATION_KEY_LENGTH = 200;
const MAXIMUM_NOTE_LENGTH = 4000;

export type StoryReferenceRow = Record<string, unknown> & {
  id: string;
  predicate?: string | null;
  subjectKind?: string | null;
  objectKind?: string | null;
  metadata?: unknown;
};

export type StoryReferenceRoleStore = {
  getRelation(relationId: string): Promise<StoryReferenceRow | null>;
  /** Writes exactly these fields of an existing row: `id`, `metadata`, `updatedAt`. */
  updateRelation(patch: { id: string; metadata: string; updatedAt: string }): Promise<void>;
};

export type StoryReferenceRoleResult = { ok: boolean; relationId: string; role: string; previousRole: string | null; citationKey: string | null };

export type StoryReferenceRoleInput = {
  relationId: string;
  role: string;
  /** The caller's Cognito groups. The schema already admits only editor and admin; this repeats it so a rule loosened by mistake does not open the route. */
  callerGroups: readonly string[];
  citationKey?: string | null;
  note?: string | null;
  /** Who made the change: the signed-in person's name from the token, never a name the caller supplies. */
  actor: string;
  now: string;
  /** Where the change was made ("cli", "newsroom", "signed-in"), from the token's client. */
  origin?: string | null;
};

function parseMetadata(value: unknown): Record<string, unknown> {
  if (typeof value === "string" && value.trim()) {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  }
  return value && typeof value === "object" && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {};
}

function optionalText(value: string | null | undefined, name: string, limit: number): string | null {
  const text = typeof value === "string" ? value.trim() : "";
  if (text.length > limit) throw new Error(`${name} is at most ${limit} characters.`);
  return text || null;
}

/** JSON with sorted keys, the way the Python writer stores `metadata` (`json.dumps(..., sort_keys=True)`). */
function sortedJson(value: Record<string, unknown>): string {
  return JSON.stringify(Object.fromEntries(Object.keys(value).sort().map((key) => [key, value[key]])));
}

export function isStoryReferenceRow(row: StoryReferenceRow, metadata: Record<string, unknown>): boolean {
  return row.predicate === STORY_REFERENCE_PREDICATE && row.subjectKind === "item" && row.objectKind === "reference" && metadata.kind === STORY_REFERENCE_KIND;
}

export async function setStoryReferenceRole(store: StoryReferenceRoleStore, input: StoryReferenceRoleInput): Promise<StoryReferenceRoleResult> {
  if (!hasEditorRights(input.callerGroups)) throw new Error("Only an editor or administrator can change a Story source's role.");
  if (!STORY_REFERENCE_ROLES.includes(input.role)) throw new Error(`role must be one of ${STORY_REFERENCE_ROLES.join(", ")}.`);
  const actor = input.actor.trim();
  if (!actor) throw new Error("Sign in to change a Story's source.");
  const citationKey = optionalText(input.citationKey, "citationKey", MAXIMUM_CITATION_KEY_LENGTH);
  const note = optionalText(input.note, "note", MAXIMUM_NOTE_LENGTH);
  const row = await store.getRelation(input.relationId);
  if (!row) throw new Error(`Story source not found: ${input.relationId}. Attach it first; attaching a new source needs no special route.`);
  const previous = parseMetadata(row.metadata);
  if (!isStoryReferenceRow(row, previous)) {
    throw new Error(`${input.relationId} is not a source attached to a Story; only a Story source's role can be changed here.`);
  }
  const previousRole = typeof previous.role === "string" ? previous.role : null;
  // The strongest statement about a reference is never weakened by a later citation (the Python writer keeps the same rule).
  const role = previousRole === BASED_ON ? BASED_ON : input.role;
  const metadata: Record<string, unknown> = { ...previous, role, updatedBy: actor, updatedAt: input.now };
  if (citationKey) metadata.citationKey = citationKey;
  if (note) metadata.note = note;
  if (input.origin) metadata.updatedVia = input.origin;
  await store.updateRelation({ id: input.relationId, metadata: sortedJson(metadata), updatedAt: input.now });
  return { ok: true, relationId: input.relationId, role, previousRole, citationKey: (metadata.citationKey as string | undefined) ?? null };
}
