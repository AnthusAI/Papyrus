import { createHash } from "node:crypto";

export type SiteBackendFeatureFlags = {
  consoleResponder: boolean;
  inboundEmail: boolean;
  slack: boolean;
  storageBackups: boolean;
};

export type SiteBackendFeatureInput = Partial<SiteBackendFeatureFlags> | undefined;

export function sanitizeAwsName(value: string, maxLength = 50): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, maxLength);
}

export function readBooleanEnvFlag(
  environment: Record<string, string | undefined>,
  name: string,
  defaultValue: boolean,
): boolean {
  const raw = (environment[name] ?? "").trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(raw)) return true;
  if (["0", "false", "no", "off"].includes(raw)) return false;
  return defaultValue;
}

export type SiteBackendIdentity = {
  brandId: string;
  amplifyAppId: string;
  amplifyBranch: string;
  productionAppId: string;
};

/**
 * True only for the Amplify app that owns the original p.apyr.us backend. That
 * backend keeps its historical account-global names so its live resources are
 * never replaced. Every other site gets brand-scoped names.
 */
export function isLegacyProductionApp(identity: SiteBackendIdentity): boolean {
  return identity.productionAppId !== "" && identity.amplifyAppId === identity.productionAppId;
}

export function isLegacyProductionPipeline(identity: SiteBackendIdentity): boolean {
  return isLegacyProductionApp(identity) && identity.amplifyBranch === "main";
}

export function resolveSiteBackendFeatureFlags(
  features: SiteBackendFeatureInput,
  environment: Record<string, string | undefined>,
  identity: SiteBackendIdentity,
): SiteBackendFeatureFlags {
  const legacyPipeline = isLegacyProductionPipeline(identity);
  return {
    consoleResponder:
      features?.consoleResponder ?? readBooleanEnvFlag(environment, "PAPYRUS_ENABLE_CONSOLE_RESPONDER", true),
    inboundEmail:
      features?.inboundEmail ?? readBooleanEnvFlag(environment, "PAPYRUS_ENABLE_INBOUND_EMAIL", legacyPipeline),
    slack: features?.slack ?? readBooleanEnvFlag(environment, "PAPYRUS_ENABLE_SLACK", false),
    storageBackups:
      features?.storageBackups ?? readBooleanEnvFlag(environment, "PAPYRUS_ENABLE_STORAGE_BACKUPS", legacyPipeline),
  };
}

export function deriveKnowledgeVectorIndexName(identity: SiteBackendIdentity): string {
  return isLegacyProductionApp(identity)
    ? "papyrus-knowledge"
    : `papyrus-knowledge-${sanitizeAwsName(identity.brandId, 40)}`;
}

export function deriveStorageBackupVaultName(
  identity: SiteBackendIdentity,
  backupsStackName: string,
  explicitName?: string,
): string {
  const explicit = (explicitName ?? "").trim();
  if (explicit !== "") return sanitizeAwsName(explicit);
  if (isLegacyProductionPipeline(identity)) {
    return sanitizeAwsName(`papyrus-${identity.productionAppId}-main-media-backup-vault`);
  }
  const stackHash = createHash("sha256").update(backupsStackName).digest("hex").slice(0, 8);
  return `papyrus-${sanitizeAwsName(identity.brandId, 20)}-${stackHash}-media-vault`;
}

/**
 * The `papyrus-site-inbound-` prefix keeps a brand named `p-apyr-us` from
 * colliding with the legacy `papyrus-inbound-p-apyr-us` set.
 * SES allows one ACTIVE receipt rule set per region. A non-legacy site creates
 * its own brand-named rule set and never activates it from CloudFormation.
 */
export function deriveReceiptRuleSetName(identity: SiteBackendIdentity, inboundEmailDomain: string): string {
  if (isLegacyProductionApp(identity)) {
    return `papyrus-inbound-${inboundEmailDomain.replace(/\./g, "-")}`;
  }
  return `papyrus-site-inbound-${sanitizeAwsName(identity.brandId, 40)}`;
}

/** `undefined` keeps the legacy auto-generated rule name of the live p.apyr.us rule. */
export function deriveReceiptRuleName(identity: SiteBackendIdentity): string | undefined {
  if (isLegacyProductionApp(identity)) return undefined;
  return `${sanitizeAwsName(identity.brandId, 40)}-inbound-submissions`;
}

export type InboundEmailSesPlan = {
  createReceiptRules: boolean;
  activateReceiptRuleSet: boolean;
  manageDomainIdentity: boolean;
};

export function planInboundEmailSes(
  identity: SiteBackendIdentity,
  inboundEmailEnabled: boolean,
  options: { manageDomainIdentity?: boolean } | undefined,
): InboundEmailSesPlan {
  const legacyPipeline = isLegacyProductionPipeline(identity);
  const deployedMainBranch = identity.amplifyAppId !== "" && identity.amplifyBranch === "main";
  const createReceiptRules = inboundEmailEnabled && (legacyPipeline || deployedMainBranch);
  return {
    createReceiptRules,
    activateReceiptRuleSet: createReceiptRules && legacyPipeline,
    manageDomainIdentity: createReceiptRules && (legacyPipeline || options?.manageDomainIdentity === true),
  };
}

export type SiteGlobalResourceNames = {
  knowledgeVectorIndexName: string;
  storageBackupVaultName: string;
  receiptRuleSetName: string;
  receiptRuleName: string | undefined;
};

export function deriveSiteGlobalResourceNames(
  identity: SiteBackendIdentity,
  inboundEmailDomain: string,
  backupsStackName: string,
): SiteGlobalResourceNames {
  return {
    knowledgeVectorIndexName: deriveKnowledgeVectorIndexName(identity),
    storageBackupVaultName: deriveStorageBackupVaultName(identity, backupsStackName),
    receiptRuleSetName: deriveReceiptRuleSetName(identity, inboundEmailDomain),
    receiptRuleName: deriveReceiptRuleName(identity),
  };
}
