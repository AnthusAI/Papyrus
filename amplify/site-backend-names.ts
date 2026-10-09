import { createHash } from "node:crypto";
import { Token } from "aws-cdk-lib";

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

/**
 * Account-global names are immutable in AWS, so they must be built from literal
 * synth-time inputs only. A CDK token (or text that came from one, such as
 * `token-token-17565`) makes the name change on every synth and fail with
 * AlreadyExists, so this throws instead.
 */
export function assertLiteralResourceName(label: string, name: string): string {
  if (Token.isUnresolved(name) || /token|\$\{/i.test(name)) {
    throw new Error(
      `${label} "${name}" is derived from an unresolved CDK token. Build account-global names from literal site config values only.`,
    );
  }
  return name;
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
  const name = isLegacyProductionApp(identity)
    ? "papyrus-knowledge"
    : `papyrus-knowledge-${sanitizeAwsName(identity.brandId, 40)}`;
  return assertLiteralResourceName("Knowledge vector index name", name);
}

export function deriveStorageBackupVaultName(identity: SiteBackendIdentity, explicitName?: string): string {
  const explicit = (explicitName ?? "").trim();
  if (explicit !== "") return assertLiteralResourceName("Backup vault name", sanitizeAwsName(explicit));
  if (isLegacyProductionPipeline(identity)) {
    return assertLiteralResourceName(
      "Backup vault name",
      sanitizeAwsName(`papyrus-${identity.productionAppId}-main-media-backup-vault`),
    );
  }
  const literalSiteKey = [identity.brandId, identity.amplifyAppId, identity.amplifyBranch].join("|");
  const siteHash = createHash("sha256").update(literalSiteKey).digest("hex").slice(0, 8);
  return assertLiteralResourceName(
    "Backup vault name",
    `papyrus-${sanitizeAwsName(identity.brandId, 20)}-${siteHash}-media-vault`,
  );
}

/**
 * The `papyrus-site-inbound-` prefix keeps a brand named `p-apyr-us` from
 * colliding with the legacy `papyrus-inbound-p-apyr-us` set.
 * SES allows one ACTIVE receipt rule set per region. A non-legacy site creates
 * its own brand-named rule set and never activates it from CloudFormation.
 */
export function deriveReceiptRuleSetName(identity: SiteBackendIdentity, inboundEmailDomain: string): string {
  const name = isLegacyProductionApp(identity)
    ? `papyrus-inbound-${inboundEmailDomain.replace(/\./g, "-")}`
    : `papyrus-site-inbound-${sanitizeAwsName(identity.brandId, 40)}`;
  return assertLiteralResourceName("Receipt rule set name", name);
}

/** `undefined` keeps the legacy auto-generated rule name of the live p.apyr.us rule. */
export function deriveReceiptRuleName(identity: SiteBackendIdentity): string | undefined {
  if (isLegacyProductionApp(identity)) return undefined;
  return assertLiteralResourceName("Receipt rule name", `${sanitizeAwsName(identity.brandId, 40)}-inbound-submissions`);
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
): SiteGlobalResourceNames {
  return {
    knowledgeVectorIndexName: deriveKnowledgeVectorIndexName(identity),
    storageBackupVaultName: deriveStorageBackupVaultName(identity),
    receiptRuleSetName: deriveReceiptRuleSetName(identity, inboundEmailDomain),
    receiptRuleName: deriveReceiptRuleName(identity),
  };
}
