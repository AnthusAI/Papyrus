import { createHash } from "node:crypto";

/** Wake keys (docs/design/always-on-agents-architecture.md, slice A2). The run record's id is derived from the key, so one wake is one record. */
const SEPARATOR = "|";
const MAX_KEY_CHARACTERS = 1000;

export function assertWakeKey(value: unknown): string {
  if (typeof value !== "string" || !value) throw new Error("A run needs a wake key.");
  const parts = value.split(SEPARATOR);
  if (value.length > MAX_KEY_CHARACTERS || (parts.length !== 3 && parts.length !== 4) || parts.some((part) => !part.trim())) {
    throw new Error(`"${value}" is not a wake key.`);
  }
  if (parts.length === 3 && parts[1] !== "schedule" && parts[1] !== "manual") {
    throw new Error(`"${value}" has three parts, so its second part must be "schedule" or "manual".`);
  }
  return value;
}

export function runIdForWakeKey(wakeKey: string): string {
  return `procedure-run-wake-${createHash("sha256").update(assertWakeKey(wakeKey)).digest("hex").slice(0, 32)}`;
}

const CONDITIONAL_TYPE = /(^|[:.#\s])ConditionalCheckFailedException$/;
const CONDITIONAL_TEXT = /conditional request failed|ConditionalCheckFailed/i;
const TYPE_FIELDS = ["errorType", "name", "code", "__type"] as const;
const NESTED_FIELDS = ["originalError", "cause", "extensions", "errorInfo", "errors"] as const;

/**
 * True when a create was refused because a record with that id already exists: any error in the answer, or nested inside one, whose type is
 * DynamoDB's conditional-check failure (the data API names it `DynamoDB:ConditionalCheckFailedException` in `errorType`) or whose text says so.
 * Any other error, or an error of a shape not listed here, is not a duplicate; the caller then throws it, so a miss is a false failure and
 * never a second run.
 */
export function isAlreadyCreated(errors: ReadonlyArray<unknown> | null | undefined): boolean {
  return (errors ?? []).some((error) => isConditionalFailure(error, new Set()));
}

function isConditionalFailure(error: unknown, seen: Set<unknown>): boolean {
  if (typeof error === "string") return CONDITIONAL_TEXT.test(error);
  if (!error || typeof error !== "object" || seen.has(error)) return false;
  seen.add(error);
  const record = error as Record<string, unknown>;
  if (typeof record.message === "string" && CONDITIONAL_TEXT.test(record.message)) return true;
  if (TYPE_FIELDS.some((field) => typeof record[field] === "string" && CONDITIONAL_TYPE.test(record[field] as string))) return true;
  return NESTED_FIELDS.some((field) => {
    const nested = record[field];
    return Array.isArray(nested) ? nested.some((entry) => isConditionalFailure(entry, seen)) : isConditionalFailure(nested, seen);
  });
}
