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

/** True when a create was refused because a record with that id already exists. */
export function isAlreadyCreated(errors: ReadonlyArray<{ message?: string | null } | string | null> | null | undefined): boolean {
  return (errors ?? []).some((error) => /conditional request failed|ConditionalCheckFailed/i.test(typeof error === "string" ? error : error?.message ?? ""));
}
