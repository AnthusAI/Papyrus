import assert from "node:assert/strict";
import {
  deriveKnowledgeVectorIndexName,
  deriveReceiptRuleName,
  deriveReceiptRuleSetName,
  deriveSiteGlobalResourceNames,
  deriveStorageBackupVaultName,
  planInboundEmailSes,
  resolveSiteBackendFeatureFlags,
  sanitizeAwsName,
  type SiteBackendIdentity,
} from "../amplify/site-backend-names";

const legacyAppId = "dbsyytcm9drqa";
const legacyMain: SiteBackendIdentity = {
  brandId: "papyrus",
  amplifyAppId: legacyAppId,
  amplifyBranch: "main",
  productionAppId: legacyAppId,
};
const newSiteMain: SiteBackendIdentity = {
  brandId: "p-apyr-us",
  amplifyAppId: "d2newsiteapp1",
  amplifyBranch: "main",
  productionAppId: "",
};
const otherSiteMain: SiteBackendIdentity = {
  brandId: "pilobol-us",
  amplifyAppId: "d1od6t7lzbwanr",
  amplifyBranch: "main",
  productionAppId: "",
};
const sandbox: SiteBackendIdentity = {
  brandId: "p-apyr-us",
  amplifyAppId: "",
  amplifyBranch: "",
  productionAppId: "",
};
const domain = "p.apyr.us";

assert.equal(sanitizeAwsName("My Site_1!!", 50), "my-site-1");

assert.equal(deriveKnowledgeVectorIndexName(legacyMain), "papyrus-knowledge");
assert.equal(deriveKnowledgeVectorIndexName(newSiteMain), "papyrus-knowledge-p-apyr-us");
assert.equal(deriveReceiptRuleSetName(legacyMain, domain), "papyrus-inbound-p-apyr-us");
assert.equal(deriveReceiptRuleName(legacyMain), undefined);
assert.equal(deriveStorageBackupVaultName(legacyMain, "stack"), `papyrus-${legacyAppId}-main-media-backup-vault`);

assert.equal(deriveReceiptRuleSetName(newSiteMain, domain), "papyrus-site-inbound-p-apyr-us");
assert.notEqual(deriveReceiptRuleSetName(newSiteMain, domain), deriveReceiptRuleSetName(legacyMain, domain));
assert.notEqual(
  deriveReceiptRuleSetName({ ...newSiteMain, brandId: "papyrus" }, domain),
  deriveReceiptRuleSetName(legacyMain, domain),
);

const siteNames = [legacyMain, newSiteMain, otherSiteMain].map((identity, index) =>
  deriveSiteGlobalResourceNames(identity, domain, `amplify-app${index}-main-branch-abc-storagebackups-XYZ`),
);
for (const key of ["knowledgeVectorIndexName", "storageBackupVaultName"] as const) {
  const values = siteNames.map((names) => names[key]);
  assert.equal(new Set(values).size, values.length, `${key} must be unique across sites: ${values.join(",")}`);
}
const newSiteNames = siteNames.slice(1);
assert.equal(
  new Set(newSiteNames.map((names) => names.receiptRuleSetName)).size,
  newSiteNames.length,
  "receipt rule set names must be unique across new sites",
);
assert.equal(new Set(newSiteNames.map((names) => names.receiptRuleName)).size, newSiteNames.length);
for (const names of siteNames) {
  assert.ok(names.storageBackupVaultName.length <= 50, names.storageBackupVaultName);
  assert.ok(names.receiptRuleSetName.length <= 64, names.receiptRuleSetName);
}

const sameBrandTwoBranchVaults = [
  deriveStorageBackupVaultName(newSiteMain, "amplify-d2newsiteapp1-main-branch-aaa-storagebackups"),
  deriveStorageBackupVaultName(newSiteMain, "amplify-d2newsiteapp1-main-branch-bbb-storagebackups"),
];
assert.notEqual(sameBrandTwoBranchVaults[0], sameBrandTwoBranchVaults[1]);
assert.equal(deriveStorageBackupVaultName(newSiteMain, "s", " my vault "), "my-vault");

assert.deepEqual(planInboundEmailSes(newSiteMain, false, undefined), {
  createReceiptRules: false,
  activateReceiptRuleSet: false,
  manageDomainIdentity: false,
});
assert.deepEqual(planInboundEmailSes(newSiteMain, true, undefined), {
  createReceiptRules: true,
  activateReceiptRuleSet: false,
  manageDomainIdentity: false,
});
assert.equal(planInboundEmailSes(newSiteMain, true, { manageDomainIdentity: true }).manageDomainIdentity, true);
assert.equal(planInboundEmailSes(newSiteMain, true, undefined).activateReceiptRuleSet, false);
assert.equal(planInboundEmailSes(sandbox, true, undefined).createReceiptRules, false);
assert.equal(planInboundEmailSes({ ...newSiteMain, amplifyBranch: "staging" }, true, undefined).createReceiptRules, false);
assert.deepEqual(planInboundEmailSes(legacyMain, true, undefined), {
  createReceiptRules: true,
  activateReceiptRuleSet: true,
  manageDomainIdentity: true,
});

const allOff = {
  PAPYRUS_ENABLE_CONSOLE_RESPONDER: "false",
  PAPYRUS_ENABLE_SLACK: "false",
  PAPYRUS_ENABLE_INBOUND_EMAIL: "false",
  PAPYRUS_ENABLE_STORAGE_BACKUPS: "false",
};
assert.deepEqual(resolveSiteBackendFeatureFlags(undefined, allOff, newSiteMain), {
  consoleResponder: false,
  inboundEmail: false,
  slack: false,
  storageBackups: false,
});
assert.deepEqual(
  resolveSiteBackendFeatureFlags(undefined, { ...allOff, PAPYRUS_ENABLE_INBOUND_EMAIL: "true", PAPYRUS_ENABLE_STORAGE_BACKUPS: "1" }, newSiteMain),
  { consoleResponder: false, inboundEmail: true, slack: false, storageBackups: true },
);
assert.equal(
  resolveSiteBackendFeatureFlags({ inboundEmail: false }, { PAPYRUS_ENABLE_INBOUND_EMAIL: "true" }, newSiteMain).inboundEmail,
  false,
  "site config wins over environment",
);
const defaultsNewSite = resolveSiteBackendFeatureFlags(undefined, {}, newSiteMain);
assert.equal(defaultsNewSite.inboundEmail, false);
assert.equal(defaultsNewSite.storageBackups, false);
assert.equal(defaultsNewSite.slack, false);
const defaultsLegacy = resolveSiteBackendFeatureFlags(undefined, {}, legacyMain);
assert.equal(defaultsLegacy.inboundEmail, true);
assert.equal(defaultsLegacy.storageBackups, true);

console.log("site backend names: ok");
