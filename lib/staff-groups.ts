/**
 * Who counts as newsroom staff. `admin` has every editor right: a site owner who is in `admin` but not `editor` can do
 * everything an editor can. Every editor check in the browser and in the Lambdas reads this one list.
 */
export const STAFF_GROUPS = ["editor", "admin"] as const;

/** True when any group is `editor` or `admin`. */
export function hasEditorRights(groups: Iterable<unknown> | null | undefined): boolean {
  if (!groups) return false;
  for (const group of groups) {
    if (typeof group === "string" && (STAFF_GROUPS as readonly string[]).includes(group.trim().toLowerCase())) return true;
  }
  return false;
}

/**
 * Cognito groups from a `cognito:groups` claim, which arrives as an array, a JSON array, a bracketed list
 * (`[admin Google_123]`), or a comma or space separated string depending on who forwarded it.
 */
export function claimGroups(value: unknown): string[] {
  const raw = Array.isArray(value) ? value.map((entry) => String(entry)) : typeof value === "string" ? value.split(/[\s,]+/) : [];
  return raw.map((entry) => entry.trim().replace(/^["'[\](){}]+|["'[\](){}]+$/g, "")).filter(Boolean);
}
