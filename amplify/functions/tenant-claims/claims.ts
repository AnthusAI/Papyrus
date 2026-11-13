/**
 * The tenant claims a session token carries (PPY-0bb0fd, docs/multi-tenancy.md "Session claims").
 *
 * One claim per role the person holds on the one tenant the session acts for, each holding the tenant id. The role names and
 * claim names are the ones `shared/tenant-context.ts` reads, so a token built here is exactly what that builder accepts.
 */
import { isSharedStack, tenantIdFromEnvironment, validateTenantId } from "../../../lib/tenant-keys";
import { TENANCY_MODELS_ENVIRONMENT_VARIABLE } from "./environment";
import { ROLE_CLAIMS, type TenantRole } from "../shared/tenant-context";

/** A membership counts only while its status is this value (src/papyrus_content/tenant_records.py). */
export const ACTIVE_MEMBERSHIP_STATUS = "active";

/** The Cognito groups a dedicated stack maps to a role claim; there is no group for `member`. */
const GROUP_ROLES: readonly TenantRole[] = ["admin", "editor", "curator"];

export type Row = Record<string, unknown>;
export type TenancyModel = "TenantMembership" | "TenantSelection";
/** Reads one row of a tenancy model by its id (a GetItem), or null when there is none. */
export type ItemReader = (model: TenancyModel, id: string) => Promise<Row | null>;

export type ClaimEnvironment = {
  shared: boolean;
  /** A dedicated stack's fixed tenant; null when it has none, and always null on a shared stack. */
  fixedTenantId: string | null;
  /** Whether the TenantMembership and TenantSelection models are deployed on this stack. */
  tenancyModels: boolean;
};

export function claimEnvironment(environment: Record<string, string | undefined>): ClaimEnvironment {
  const shared = isSharedStack(environment);
  return {
    shared,
    fixedTenantId: shared ? null : tenantIdFromEnvironment(environment) ?? null,
    tenancyModels: environment[TENANCY_MODELS_ENVIRONMENT_VARIABLE]?.trim() === "true",
  };
}

function validTenantId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    return validateTenantId(value);
  } catch {
    return null;
  }
}

/** The role an active membership row of this person and tenant grants, or null. The row's own fields must agree with the key. */
export function membershipRole(row: Row | null, tenantId: string, userSub: string): TenantRole | null {
  if (!row || row.status !== ACTIVE_MEMBERSHIP_STATUS || row.tenantId !== tenantId || row.userSub !== userSub) return null;
  return ROLE_CLAIMS.find(([role]) => role === row.role)?.[0] ?? null;
}

/**
 * The tenant this session acts for. A shared stack takes the person's stored selection (the Google flow cannot pass one, so
 * the choice is written first and read here); a stored value that is not a tenant id selects nothing. A dedicated stack acts
 * for its fixed tenant whatever was selected.
 */
export async function sessionTenant(environment: ClaimEnvironment, userSub: string, read: ItemReader): Promise<string | null> {
  if (!environment.shared) return environment.fixedTenantId;
  if (!environment.tenancyModels) return null;
  const selection = await read("TenantSelection", userSub);
  return validTenantId(selection?.selectedTenantId);
}

/** Roles a person holds on a dedicated stack through their Cognito groups. A shared stack never reads groups for a tenant. */
export function rolesFromGroups(groups: readonly string[]): TenantRole[] {
  return GROUP_ROLES.filter((role) => groups.includes(role));
}

/**
 * Every claim for one sign-in or refresh: `{papyrus_tenant_<role>: tenantId}` for each role held on the session's tenant, or
 * nothing when the person has no tenant, no active membership there and (on a dedicated stack) no matching group.
 */
export async function buildTenantClaims(
  environment: ClaimEnvironment,
  person: { userSub: string; groups: readonly string[] },
  read: ItemReader,
): Promise<Record<string, string>> {
  const tenantId = await sessionTenant(environment, person.userSub, read);
  if (tenantId === null) return {};
  const roles = new Set<TenantRole>(environment.shared ? [] : rolesFromGroups(person.groups));
  if (environment.tenancyModels) {
    const role = membershipRole(await read("TenantMembership", `${tenantId}#${person.userSub}`), tenantId, person.userSub);
    if (role) roles.add(role);
  }
  const claims: Record<string, string> = {};
  for (const [role, claim] of ROLE_CLAIMS) if (roles.has(role)) claims[claim] = tenantId;
  return claims;
}
