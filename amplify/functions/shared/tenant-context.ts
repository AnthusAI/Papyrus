/**
 * The tenant a function call acts for, built once from an AppSync resolver event's identity.
 * A signed-in caller carries one tenant in its token claims (docs/plans/tenant-claims-spike-1.md); an IAM caller names it
 * explicitly. A shared stack refuses a call that cannot name exactly one tenant; a dedicated stack acts for its fixed
 * site tenant. The tenant never comes from the request body and is never guessed.
 * Python twin: src/papyrus_content/tenant_context.py; both read features_backend/fixtures/tenant-context/vectors.json.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { isSharedStack, tenantIdFromEnvironment, validateTenantId } from "../../../lib/tenant-keys";

export const ROLE_CLAIMS = [
  ["admin", "papyrus_tenant_admin"],
  ["editor", "papyrus_tenant_editor"],
  ["curator", "papyrus_tenant_curator"],
  ["member", "papyrus_tenant_member"],
] as const;

export type TenantRole = (typeof ROLE_CLAIMS)[number][0];

export type TenantRefusalReason =
  | "unsupported_identity"
  | "iam_without_tenant"
  | "no_tenant_claim"
  | "multiple_tenants"
  | "foreign_tenant"
  | "invalid_tenant"
  | "explicit_tenant_for_user";

export class TenantContextRefusal extends Error {
  constructor(readonly reason: TenantRefusalReason, message: string) {
    super(message);
    this.name = "TenantContextRefusal";
  }
}

export type TenantContext = {
  tenantId: string | null;
  roles: TenantRole[];
  mode: "shared" | "dedicated";
  operator: boolean;
};

export type TenantContextOptions = {
  /** For IAM callers only. */
  explicitTenant?: string | null;
  environment?: Record<string, string | undefined>;
};

type Identity = Record<string, unknown> | null | undefined;

function checked(tenantId: unknown): string {
  if (typeof tenantId !== "string") throw new TenantContextRefusal("invalid_tenant", "A tenant id must be a string.");
  try {
    return validateTenantId(tenantId);
  } catch (error) {
    throw new TenantContextRefusal("invalid_tenant", (error as Error).message);
  }
}

function claimed(claims: Record<string, unknown>): { tenant: string | null; roles: TenantRole[] } {
  const named = ROLE_CLAIMS.filter(([, claim]) => claims[claim] !== undefined && claims[claim] !== null && claims[claim] !== "");
  const tenants = new Set(named.map(([, claim]) => checked(claims[claim])));
  if (tenants.size > 1) {
    throw new TenantContextRefusal("multiple_tenants", "The claims name more than one tenant; a session acts for one tenant at a time.");
  }
  return { tenant: [...tenants][0] ?? null, roles: named.map(([role]) => role) };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function buildTenantContext(identity: Identity, options: TenantContextOptions = {}): TenantContext {
  const environment = options.environment ?? process.env;
  const explicitTenant = options.explicitTenant ?? null;
  const isUser = isRecord(identity) && isRecord(identity.claims);
  const isIam = isRecord(identity) && !isUser && ("userArn" in identity || "accountId" in identity);
  if (!isUser && !isIam) {
    throw new TenantContextRefusal("unsupported_identity", "The call carries neither a user pool identity nor an IAM identity.");
  }
  const shared = isSharedStack(environment);
  const mode = shared ? "shared" : "dedicated";
  if (isUser && explicitTenant !== null) {
    throw new TenantContextRefusal("explicit_tenant_for_user", "A signed-in caller's tenant comes from its claims, never from an argument.");
  }
  if (isIam && shared && !explicitTenant) {
    throw new TenantContextRefusal("iam_without_tenant", "An IAM call on a shared stack must name its tenant.");
  }
  const { tenant, roles } = isUser ? claimed((identity as { claims: Record<string, unknown> }).claims) : { tenant: null, roles: [] as TenantRole[] };
  const requested = isIam && explicitTenant ? checked(explicitTenant) : tenant;
  if (shared) {
    if (requested === null) throw new TenantContextRefusal("no_tenant_claim", "The caller's token carries no tenant claim.");
    return { tenantId: requested, roles, mode, operator: isIam };
  }
  const fixed = tenantIdFromEnvironment(environment) ?? null;
  if (requested !== null && requested !== fixed) {
    throw new TenantContextRefusal("foreign_tenant", "The call names a tenant other than this stack's fixed tenant.");
  }
  return { tenantId: fixed, roles, mode, operator: isIam };
}

export function isIamIdentity(identity: Identity): boolean {
  return isRecord(identity) && !isRecord(identity.claims) && ("userArn" in identity || "accountId" in identity);
}

type FieldEvent = { identity?: unknown; arguments?: Record<string, unknown> | null };

/**
 * The one context of an AppSync field event. A signed-in caller's tenant is its role claim and nothing in the arguments is read for it. An IAM
 * caller (the platform operator or a worker) names the tenant as the `tenantId` argument; an operation without that argument cannot be called by
 * IAM on a shared stack, which refuses it before any read.
 */
export function buildEventTenantContext(event: FieldEvent, environment: Record<string, string | undefined> = process.env): TenantContext {
  const identity = event.identity as Identity;
  const named = isIamIdentity(identity) ? event.arguments?.tenantId : undefined;
  return buildTenantContext(identity, { explicitTenant: (named ?? null) as string | null, environment });
}

const acting = new AsyncLocalStorage<TenantContext>();

/** Run one call for `context`: everything it awaits reads the tenant from `currentTenantContext()`, never from the environment. */
export function actingFor<T>(context: TenantContext, call: () => T): T {
  return acting.run(context, call);
}

export function currentTenantContext(): TenantContext {
  const context = acting.getStore();
  if (!context) {
    throw new TenantContextRefusal("unsupported_identity", "No tenant context: a handler builds one from the event before it reads or writes anything.");
  }
  return context;
}
