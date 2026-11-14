import { contentHashParameterName, skillIdParameterName, type AlexaConfig } from "../config";
import {
  accountLinkingRequest,
  contentHash,
  generateSkillPackage,
  interactionModelPath,
  missingManifestInputs,
  skillLocales,
  SKILL_MANIFEST_PATH,
  stableJson,
  type AccountLinkingOutputs,
} from "../skill-package";
import type { SyncPorts } from "./ports";

/** The shared Anthus Amazon developer account's credentials: one set for every site. Created once, by hand, in SecureString parameters. */
export const LWA_CLIENT_ID_PARAMETER = "/papyrus/alexa/lwa-client-id";
export const LWA_CLIENT_SECRET_PARAMETER = "/papyrus/alexa/lwa-client-secret";
export const LWA_REFRESH_TOKEN_PARAMETER = "/papyrus/alexa/lwa-refresh-token";
export const VENDOR_ID_PARAMETER = "/papyrus/alexa/vendor-id";
export const ALEXA_CREDENTIAL_PARAMETERS = [LWA_CLIENT_ID_PARAMETER, LWA_CLIENT_SECRET_PARAMETER, LWA_REFRESH_TOKEN_PARAMETER, VENDOR_ID_PARAMETER] as const;

export type SyncInput = {
  config: AlexaConfig;
  /** `custom.alexa.functionArn`. */
  endpointArn: string;
  /** `custom.alexa.accountLinking`, when the Cognito task published it. */
  accountLinking?: AccountLinkingOutputs;
};

export type SyncResult =
  | { status: "skipped"; reason: "no-credentials" | "incomplete-config" }
  | { status: "unchanged"; skillId: string }
  | { status: "created" | "updated"; skillId: string };

function permissionStatementId(skillId: string): string {
  return `AlexaSkillInvoke-${contentHash(skillId).slice(0, 12)}`;
}

/**
 * Makes sure the skill ID is the only skill that can invoke the function: adds a skill-scoped permission, then removes the
 * unconditional (or other-skill) Alexa statements. Idempotent, so it runs on every deploy and heals a CloudFormation redeploy
 * that put the unconditional statement back. It is a Lambda API call, not an Amazon one.
 */
async function scopePermission(ports: SyncPorts, functionArn: string, skillId: string): Promise<void> {
  const statements = await ports.permissions.alexaStatements(functionArn);
  if (!statements.some((statement) => statement.skillId === skillId)) {
    await ports.permissions.addSkillPermission(functionArn, permissionStatementId(skillId), skillId);
    ports.log(`alexa-sync: the function now accepts only skill ${skillId} from the Alexa service`);
  }
  for (const statement of statements) {
    if (statement.skillId !== skillId) await ports.permissions.removePermission(functionArn, statement.statementId);
  }
}

/**
 * The deploy-time sync (docs/alexa.md): create the skill the first time, update it only when the generated content changed.
 * It never throws for a missing prerequisite (no credentials, incomplete config): it logs one line and skips, so a site's deploy is
 * never broken by Alexa. A refusal from Amazon does throw, and the caller decides what a failure means for the deploy.
 */
export async function syncAlexaSkill(input: SyncInput, ports: SyncPorts): Promise<SyncResult> {
  const { config, endpointArn } = input;
  const missing = missingManifestInputs(config);
  if (missing.length > 0) {
    ports.log(`alexa-sync: skipped, the skill manifest needs ${missing.join(", ")} in the alexa plugin settings`);
    return { status: "skipped", reason: "incomplete-config" };
  }

  const [clientId, clientSecret, refreshToken, vendorId] = await Promise.all(ALEXA_CREDENTIAL_PARAMETERS.map((name) => ports.parameters.get(name)));
  if (clientId === undefined || clientSecret === undefined || refreshToken === undefined || vendorId === undefined) {
    ports.log(`alexa-sync: skipped, the Amazon developer credentials are not in SSM (${ALEXA_CREDENTIAL_PARAMETERS.join(", ")})`);
    return { status: "skipped", reason: "no-credentials" };
  }

  const files = generateSkillPackage(config, { endpointArn });
  const manifest = JSON.parse(files[SKILL_MANIFEST_PATH]);
  const locales = skillLocales(config);

  let linking: ReturnType<typeof accountLinkingRequest> | undefined;
  if (config.accountLinking) {
    const secret = input.accountLinking === undefined ? undefined : await ports.clientSecrets.clientSecret(input.accountLinking);
    if (input.accountLinking === undefined) ports.log("alexa-sync: account linking is on but custom.alexa.accountLinking is not in the outputs yet; the skill is synced without it");
    else if (secret === undefined) ports.log("alexa-sync: the Alexa Cognito client has no secret; the skill is synced without account linking");
    else linking = accountLinkingRequest(input.accountLinking, secret);
  }

  const hash = contentHash(files[SKILL_MANIFEST_PATH], ...locales.map((locale) => files[interactionModelPath(locale)]), linking === undefined ? "" : stableJson(linking));
  const storedSkillId = config.skillId ?? ((await ports.parameters.get(skillIdParameterName(config)))?.trim() || undefined);
  const hashParameter = contentHashParameterName(config);

  if (storedSkillId !== undefined && (await ports.parameters.get(hashParameter)) === hash) {
    await scopePermission(ports, endpointArn, storedSkillId);
    ports.log(`alexa-sync: skill ${storedSkillId} is up to date`);
    return { status: "unchanged", skillId: storedSkillId };
  }

  const smapi = await ports.connect({ clientId, clientSecret, refreshToken });
  let skillId = storedSkillId;
  let created = false;
  if (skillId === undefined) {
    skillId = await smapi.createSkill(vendorId, manifest);
    created = true;
    // Stored before anything else can fail, so a retry updates this skill instead of creating a second one.
    await ports.parameters.putString(skillIdParameterName(config), skillId);
    ports.log(`alexa-sync: created skill ${skillId}`);
  } else {
    await smapi.updateManifest(skillId, manifest);
  }
  await scopePermission(ports, endpointArn, skillId);
  const model = JSON.parse(files[interactionModelPath(locales[0])]);
  for (const locale of locales) await smapi.putInteractionModel(skillId, locale, model);
  if (linking !== undefined) await smapi.putAccountLinking(skillId, linking);
  await ports.parameters.putString(hashParameter, hash);
  ports.log(`alexa-sync: ${created ? "uploaded" : "updated"} the manifest and interaction model of skill ${skillId}${linking === undefined ? "" : " and its account linking"}`);
  return { status: created ? "created" : "updated", skillId };
}
