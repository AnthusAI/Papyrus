/**
 * An editor's review of knowledge nodes from the signed-in CLI: `papyrus knowledge entities accept | reject | rename | alias | describe |
 * accept-description | page`.
 *
 * Those commands work out the change as small patches (src/papyrus_content/knowledge_snapshot/entity_review.py) and used to write them to the `SemanticNode`
 * and `SemanticRelation` models directly. An editor's token may read those models and nothing more (the write rules are AWS credentials only), so the
 * write failed with "Failed to apply update SemanticNode". The model rules stay as they are: this checks each patch against a short list of what a
 * review may change and writes it, for editors only. It adds no way to create, retire or move a node or a relation.
 *
 * A review keeps who decided in the node's `changeReason` (a marker, then one JSON object: `acceptedBy`, `rejectedBy`, `descriptionEditedBy`, `retypedBy`,
 * `aliasedBy`, and `pageGivenBy` or `pageTakenBy` when an editor decides against the extractor's page answer, each an `{actor, name, on}`). The CLI lets the person say `--actor ai|human`, and a script in an editor's session can say anything, so
 * every actor written or changed by a call is stamped `via` with the origin the token proves (`edit-origin.ts`: cli, newsroom, signed-in); an actor the
 * call did not change keeps the `via` it already had. A reader can tell a decision made in the Newsroom from one made through the CLI.
 */

export const REVIEW_MARKER = "papyrus-knowledge-review@1:";
export const REVIEW_ACTOR_KEYS = ["acceptedBy", "rejectedBy", "descriptionEditedBy", "retypedBy", "aliasedBy", "pageGivenBy", "pageTakenBy"] as const;
const ACTORS = ["ai", "human"] as const;
const REVIEW_STATUSES = ["accepted", "rejected", "generated"] as const;
const MAXIMUM_PATCHES = 200;
const MAXIMUM_NAME_LENGTH = 200;
const MAXIMUM_ALIASES = 100;
const MAXIMUM_DESCRIPTION_LENGTH = 4000;
const MAXIMUM_ACTOR_NAME_LENGTH = 80;
const EMAIL = /[^\s@]+@[^\s@]+\.[^\s@]+/;

type Json = Record<string, unknown>;

export type ReviewPatch = { modelName: string; expected: Json };

export type KnowledgeReviewStore = {
  getNode(id: string): Promise<(Json & { id: string }) | null>;
  updateNode(patch: Json): Promise<void>;
  getRelation(id: string): Promise<(Json & { id: string }) | null>;
  updateRelation(patch: Json): Promise<void>;
};

export type KnowledgeReviewResult = { ok: boolean; applied: number; origin: string };

function isObject(value: unknown): value is Json {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** The review marks in a node's `changeReason`: an object of the known actor keys, or none when the text is not a review marker. */
export function decodeReviewMarks(changeReason: unknown): Json {
  if (typeof changeReason !== "string" || !changeReason.startsWith(REVIEW_MARKER)) return {};
  try {
    const parsed = JSON.parse(changeReason.slice(REVIEW_MARKER.length));
    return isObject(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function encodeReviewMarks(marks: Json): string {
  return REVIEW_MARKER + JSON.stringify(marks);
}

function sameActor(first: unknown, second: unknown): boolean {
  if (!isObject(first) || !isObject(second)) return false;
  return first.actor === second.actor && (first.name ?? null) === (second.name ?? null) && first.on === second.on;
}

function validActor(value: unknown, key: string): Json {
  if (!isObject(value) || !ACTORS.includes(value.actor as (typeof ACTORS)[number]) || typeof value.on !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.on)) {
    throw new Error(`${key} is not a reviewer in the shape {actor: ai|human, name, on: YYYY-MM-DD}.`);
  }
  const name = value.name;
  if (name !== null && name !== undefined) {
    if (typeof name !== "string" || name.length > MAXIMUM_ACTOR_NAME_LENGTH || EMAIL.test(name)) throw new Error(`${key} has a reviewer name that is too long or holds an email address.`);
  }
  return { actor: value.actor, name: name ?? null, on: value.on };
}

/**
 * The `changeReason` to store for a patch: the actors the patch changed are stamped with the proven origin, the ones it left alone keep what is stored,
 * and anything that is not a review marker is refused (the field is not free text here).
 */
export function stampedChangeReason(proposed: unknown, stored: unknown, origin: string): string {
  if (typeof proposed !== "string" || !proposed.startsWith(REVIEW_MARKER)) throw new Error("A review changes the change reason only by its review marks.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(proposed.slice(REVIEW_MARKER.length));
  } catch {
    throw new Error("The review marks are not valid JSON.");
  }
  if (!isObject(parsed)) throw new Error("The review marks are not a JSON object.");
  const before = decodeReviewMarks(stored);
  const marks: Json = {};
  for (const key of Object.keys(parsed)) {
    if (!(REVIEW_ACTOR_KEYS as readonly string[]).includes(key)) throw new Error(`The review marks hold ${key}, which a review does not write.`);
  }
  for (const key of REVIEW_ACTOR_KEYS) {
    const value = parsed[key];
    if (value === null || value === undefined) {
      if (key === "acceptedBy" || key === "rejectedBy" || key === "descriptionEditedBy") marks[key] = null;
      continue;
    }
    const actor = validActor(value, key);
    marks[key] = sameActor(actor, before[key]) ? before[key] : { ...actor, via: origin };
  }
  return encodeReviewMarks(marks);
}

/** The stored `changeReason` once the node's description has been replaced by words nobody has accepted: the description mark goes, the rest stays. */
export function changeReasonAfterNewDescription(stored: unknown, fallback: string): string {
  const marks = decodeReviewMarks(stored);
  if (!Object.keys(marks).length) return fallback;
  return encodeReviewMarks({ ...marks, descriptionEditedBy: null });
}

function text(value: unknown, key: string, maximum: number): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${key} must be words.`);
  if (value.length > maximum) throw new Error(`${key} is at most ${maximum} characters.`);
  if (EMAIL.test(value)) throw new Error(`${key} must not hold an email address.`);
  return value;
}

async function nodePatch(store: KnowledgeReviewStore, expected: Json, origin: string): Promise<Json> {
  const id = text(expected.id, "id", 400);
  const node = await store.getNode(id);
  if (!node) throw new Error(`No SemanticNode ${id}.`);
  if (node.versionState !== undefined && node.versionState !== null && node.versionState !== "current") throw new Error(`${id} is not the current version of its entity.`);
  const allowed = ["id", "status", "displayName", "aliases", "description", "changeReason", "updatedAt"];
  for (const key of Object.keys(expected)) {
    if (!allowed.includes(key)) throw new Error(`A review does not change ${key} of a SemanticNode.`);
  }
  const patch: Json = { id };
  if ("status" in expected) {
    if (!REVIEW_STATUSES.includes(expected.status as (typeof REVIEW_STATUSES)[number])) throw new Error(`status must be one of ${REVIEW_STATUSES.join(", ")}.`);
    patch.status = expected.status;
  }
  if ("displayName" in expected) patch.displayName = text(expected.displayName, "displayName", MAXIMUM_NAME_LENGTH);
  if ("aliases" in expected) {
    const aliases = expected.aliases;
    if (!Array.isArray(aliases) || aliases.length > MAXIMUM_ALIASES) throw new Error(`aliases must be a list of at most ${MAXIMUM_ALIASES} names.`);
    patch.aliases = aliases.map((alias) => text(alias, "an alias", MAXIMUM_NAME_LENGTH));
  }
  if ("description" in expected) patch.description = text(expected.description, "description", MAXIMUM_DESCRIPTION_LENGTH);
  if ("changeReason" in expected) patch.changeReason = stampedChangeReason(expected.changeReason, node.changeReason, origin);
  if (typeof expected.updatedAt === "string") patch.updatedAt = expected.updatedAt;
  return patch;
}

async function relationPatch(store: KnowledgeReviewStore, expected: Json): Promise<Json> {
  const id = text(expected.id, "id", 400);
  const relation = await store.getRelation(id);
  if (!relation) throw new Error(`No SemanticRelation ${id}.`);
  for (const key of Object.keys(expected)) {
    if (!["id", "metadata", "updatedAt"].includes(key)) throw new Error(`A review does not change ${key} of a SemanticRelation.`);
  }
  const patch: Json = { id };
  if ("metadata" in expected) {
    let metadata: unknown;
    try {
      metadata = typeof expected.metadata === "string" ? JSON.parse(expected.metadata) : expected.metadata;
    } catch {
      throw new Error("metadata is not valid JSON.");
    }
    if (!isObject(metadata)) throw new Error("metadata must be a JSON object.");
    let stored: unknown = relation.metadata;
    if (typeof stored === "string") {
      try {
        stored = JSON.parse(stored || "{}");
      } catch {
        stored = {};
      }
    }
    // A review confirms a link; it does not turn it into another kind of link or hand its decision to someone else.
    const before = isObject(stored) ? stored : {};
    for (const key of ["kind", "decision", "decidedBy", "provenance"]) {
      if (key in before && JSON.stringify(before[key]) !== JSON.stringify(metadata[key])) throw new Error(`A review does not change ${key} of a link.`);
    }
    patch.metadata = JSON.stringify(metadata);
  }
  if (typeof expected.updatedAt === "string") patch.updatedAt = expected.updatedAt;
  return patch;
}

/**
 * Checks every patch, then writes them (nothing is written when one is refused). The caller has already been checked to be an editor or admin.
 */
export async function applyKnowledgeReview(store: KnowledgeReviewStore, input: { patches: unknown; origin: string }): Promise<KnowledgeReviewResult> {
  const patches = typeof input.patches === "string" ? JSON.parse(input.patches) : input.patches;
  if (!Array.isArray(patches) || patches.length === 0) throw new Error("There is nothing to apply.");
  if (patches.length > MAXIMUM_PATCHES) throw new Error(`A review applies at most ${MAXIMUM_PATCHES} changes at once.`);
  const checked: Array<{ model: "node" | "relation"; patch: Json }> = [];
  for (const entry of patches) {
    if (!isObject(entry) || !isObject(entry.expected)) throw new Error("Each change is {modelName, expected}.");
    if (entry.modelName === "SemanticNode") checked.push({ model: "node", patch: await nodePatch(store, entry.expected, input.origin) });
    else if (entry.modelName === "SemanticRelation") checked.push({ model: "relation", patch: await relationPatch(store, entry.expected) });
    else throw new Error(`A review changes SemanticNode and SemanticRelation, not ${String(entry.modelName)}.`);
  }
  for (const { model, patch } of checked) {
    if (model === "node") await store.updateNode(patch);
    else await store.updateRelation(patch);
  }
  return { ok: true, applied: checked.length, origin: input.origin };
}
