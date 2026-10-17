import assert from "node:assert/strict";
import { App, NestedStack, Stack, Token } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as s3 from "aws-cdk-lib/aws-s3";
import { addInboundEmailSesIntake } from "../amplify/inbound-email/ses-intake";
import {
  deriveReceiptRuleName,
  deriveReceiptRuleSetName,
  deriveStorageBackupVaultName,
  planInboundEmailSes,
  type SiteBackendIdentity,
} from "../amplify/site-backend-names";
import { addStorageBackups } from "../amplify/storage-backups/construct";

const domain = "p.apyr.us";
const sites: SiteBackendIdentity[] = [
  { brandId: "p-apyr-us", amplifyAppId: "d2newsiteapp1", amplifyBranch: "main", productionAppId: "" },
  { brandId: "pilobol-us", amplifyAppId: "d1od6t7lzbwanr", amplifyBranch: "main", productionAppId: "" },
];
const legacy: SiteBackendIdentity = {
  brandId: "papyrus",
  amplifyAppId: "dbsyytcm9drqa",
  amplifyBranch: "main",
  productionAppId: "dbsyytcm9drqa",
};

function synthSiteStack(identity: SiteBackendIdentity, options: { inbound: boolean; backups: boolean; existingRuleSet?: string }) {
  const app = new App();
  const stack = new Stack(app, `Site-${identity.brandId}`, { env: { account: "335163751677", region: "us-east-1" } });
  const bucket = new s3.Bucket(stack, "Media");
  const plan = planInboundEmailSes(identity, options.inbound, undefined);
  if (plan.createReceiptRules) {
    addInboundEmailSesIntake(stack, {
      storageBucket: bucket,
      recipients: [`submissions@${domain}`],
      ruleSetName: deriveReceiptRuleSetName(identity, domain),
      existingRuleSetName: options.existingRuleSet,
      ruleName: deriveReceiptRuleName(identity),
      activateRuleSet: plan.activateReceiptRuleSet,
      domainIdentity: plan.manageDomainIdentity
        ? { domain, hostedZoneId: "Z1", hostedZoneName: "apyr.us", recordName: "p" }
        : undefined,
    });
  }
  if (options.backups) {
    addStorageBackups(stack, {
      storageBucket: bucket,
      backupVaultName: deriveStorageBackupVaultName(identity),
    });
  }
  return Template.fromStack(stack);
}

function propertiesOf(template: Template, type: string, property: string): string[] {
  return Object.values(template.findResources(type)).map((resource) => JSON.stringify(resource.Properties?.[property]).replace(/^"|"$/g, ""));
}

const synthesized = sites.map((identity) => synthSiteStack(identity, { inbound: true, backups: true }));

const ruleSetNames = synthesized.flatMap((template) => propertiesOf(template, "AWS::SES::ReceiptRuleSet", "RuleSetName"));
const vaultNames = synthesized.flatMap((template) => propertiesOf(template, "AWS::Backup::BackupVault", "BackupVaultName"));
assert.equal(ruleSetNames.length, 2);
assert.equal(new Set(ruleSetNames).size, 2, `rule set names collide: ${ruleSetNames}`);
assert.equal(vaultNames.length, 2);
assert.equal(new Set(vaultNames).size, 2, `vault names collide: ${vaultNames}`);
const liveRuleSetName = "papyrus-inbound-p-apyr-us";
const liveVaultName = "papyrus-dbsyytcm9drqa-main-media-backup-vault";
assert.ok(!vaultNames.includes(liveVaultName));
assert.ok(!ruleSetNames.includes(liveRuleSetName), "a new site must not reuse the live rule set name");
for (const template of synthesized) {
  assert.equal(Object.keys(template.findResources("AWS::SES::ReceiptRule")).length, 1);
  const ruleNames = propertiesOf(template, "AWS::SES::ReceiptRule", "Rule").map((rule) => String(rule));
  assert.ok(ruleNames.every((rule) => rule.includes("-inbound-submissions")), ruleNames.join());
  assert.equal(Object.keys(template.findResources("Custom::AWS")).length, 0, "no SES activation or domain verification custom resources for a new site");
  assert.equal(Object.keys(template.findResources("AWS::Route53::RecordSet")).length, 0);
}

const flagsOff = synthSiteStack(sites[0], { inbound: false, backups: false });
assert.equal(Object.keys(flagsOff.findResources("AWS::SES::ReceiptRuleSet")).length, 0);
assert.equal(Object.keys(flagsOff.findResources("AWS::SES::ReceiptRule")).length, 0);
assert.equal(Object.keys(flagsOff.findResources("AWS::Backup::BackupVault")).length, 0);
assert.equal(Object.keys(flagsOff.findResources("AWS::Backup::BackupPlan")).length, 0);

const existingSet = synthSiteStack(sites[0], { inbound: true, backups: false, existingRuleSet: "shared-set" });
assert.equal(Object.keys(existingSet.findResources("AWS::SES::ReceiptRuleSet")).length, 0, "existing rule set must not be re-created");
assert.equal(Object.keys(existingSet.findResources("AWS::SES::ReceiptRule")).length, 1);
assert.deepEqual(propertiesOf(existingSet, "AWS::SES::ReceiptRule", "RuleSetName"), ["shared-set"]);

const legacyTemplate = synthSiteStack(legacy, { inbound: true, backups: true });
assert.deepEqual(propertiesOf(legacyTemplate, "AWS::SES::ReceiptRuleSet", "RuleSetName"), [liveRuleSetName]);
assert.deepEqual(propertiesOf(legacyTemplate, "AWS::Backup::BackupVault", "BackupVaultName"), [liveVaultName]);
assert.ok(
  Object.keys(legacyTemplate.findResources("Custom::AWS")).some((id) => id.startsWith("ActivateInboundEmailRuleSet")),
  "legacy keeps activating its own rule set",
);
assert.ok(
  Object.keys(legacyTemplate.findResources("AWS::Backup::BackupVault")).some((id) => id === "PapyrusStorageBackupVault" || id.startsWith("PapyrusStorageBackupVault")),
  "legacy logical ids unchanged",
);

const tokenShapedIdentity: SiteBackendIdentity = {
  brandId: "p-apyr-us",
  amplifyAppId: "d2newsiteapp1",
  amplifyBranch: "main",
  productionAppId: "",
};
function synthTokenShapedBackend() {
  const app = new App();
  const stack = new Stack(app, "amplify-d2newsiteapp1-main-branch-abc", { env: { account: "712236451410", region: "us-east-1" } });
  const nested = new NestedStack(stack, "storage-backups");
  const bucket = new s3.Bucket(stack, "Media");
  assert.ok(Token.isUnresolved(nested.stackName), "stack names are tokens at synth time");
  addStorageBackups(nested, { storageBucket: bucket, backupVaultName: deriveStorageBackupVaultName(tokenShapedIdentity) });
  addInboundEmailSesIntake(stack, {
    storageBucket: bucket,
    recipients: [`submissions@${domain}`],
    ruleSetName: deriveReceiptRuleSetName(tokenShapedIdentity, domain),
    ruleName: deriveReceiptRuleName(tokenShapedIdentity),
    activateRuleSet: false,
  });
  return [
    ...propertiesOf(Template.fromStack(nested), "AWS::Backup::BackupVault", "BackupVaultName"),
    ...propertiesOf(Template.fromStack(stack), "AWS::SES::ReceiptRuleSet", "RuleSetName"),
    ...propertiesOf(Template.fromStack(stack), "AWS::SES::ReceiptRule", "Rule"),
  ];
}
const firstSynth = synthTokenShapedBackend();
const secondSynth = synthTokenShapedBackend();
assert.equal(firstSynth.length, 3);
assert.deepEqual(firstSynth, secondSynth, "two synths of the same site must give identical names");
assert.ok(firstSynth.every((name) => !/token/i.test(name)), `names must not contain token: ${firstSynth}`);
assert.ok(firstSynth.every((name) => name.includes("p-apyr-us")), `names must contain the brand: ${firstSynth}`);

console.log("site backend synth: ok");
