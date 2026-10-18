export const TENANT_ID_ENVIRONMENT_VARIABLE = "PAPYRUS_TENANT_ID";
const TENANT_KEY_SEPARATOR = "#";
const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;

export function validateTenantId(tenantId: string): string {
  if (!TENANT_ID_PATTERN.test(tenantId)) {
    throw new Error(`Tenant id "${tenantId}" must be lowercase letters, digits and hyphens, starting with a letter or digit.`);
  }
  return tenantId;
}

export function tenantIdFromEnvironment(environment: NodeJS.ProcessEnv = process.env): string | undefined {
  const configured = environment[TENANT_ID_ENVIRONMENT_VARIABLE]?.trim();
  return configured ? validateTenantId(configured) : undefined;
}

export function tenantScopedValue(tenantId: string | undefined, value: string): string {
  if (!tenantId) return value;
  const prefix = `${tenantId}${TENANT_KEY_SEPARATOR}`;
  return value.startsWith(prefix) ? value : `${prefix}${value}`;
}

export function rowBelongsToTenant(tenantId: string | undefined, row: { tenantId?: string | null } | null | undefined): boolean {
  if (!tenantId || !row) return true;
  return row.tenantId === tenantId;
}
