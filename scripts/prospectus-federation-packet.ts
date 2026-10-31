import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DEFAULT_CLI_LOOPBACK_PORT = 53682;
export const CLI_CALLBACK_PATH = "/cli/callback";
export const AWS_EXECUTABLE_ENVIRONMENT_VARIABLE = "PAPYRUS_FEDERATION_PACKET_AWS";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export interface SiteDescription {
  site: string;
  outputsPath: string;
  profile: string;
  siteOrigin: string;
  consoleOrigin: string;
  registered: boolean;
  cliLoopbackPort: number;
}

interface AmplifyOutputs {
  auth?: { user_pool_id?: string; aws_region?: string };
  custom?: { prospectusSignIn?: { clientId?: string; callbackPath?: string } };
}

export interface GoogleOnlyFinding {
  name: string;
  holds: boolean;
  expected: string;
  actual: string;
}

export interface FederationEvidence {
  client: Record<string, unknown>;
  pool: Record<string, unknown>;
  provider: Record<string, unknown>;
}

export function refuseRepositoryOutputDirectory(outputDirectory: string): void {
  const resolved = path.resolve(outputDirectory);
  const existingAncestor = (candidate: string): string => (existsSync(candidate) ? realpathSync(candidate) : existingAncestor(path.dirname(candidate)));
  const real = path.join(existingAncestor(resolved), path.relative(existingAncestor(resolved), resolved));
  const relative = path.relative(realpathSync(repositoryRoot), real);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new Error("Refusing to write the federation packet inside the repository: it contains client and pool ids. Choose a directory outside the repository.");
  }
}

function sameList(actual: unknown, expected: string[]): boolean {
  return Array.isArray(actual) && actual.length === expected.length && expected.every((value) => actual.includes(value));
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

export function googleOnlyFindings(evidence: FederationEvidence): GoogleOnlyFinding[] {
  const { client, pool } = evidence;
  const lambdaConfig = (pool.LambdaConfig ?? {}) as Record<string, unknown>;
  const preTokenTriggers = ["PreTokenGeneration", "PreTokenGenerationConfig"].filter((key) => lambdaConfig[key] !== undefined && lambdaConfig[key] !== null);
  return [
    { name: "Supported identity providers", holds: sameList(client.SupportedIdentityProviders, ["Google"]), expected: "Google", actual: asList(client.SupportedIdentityProviders).join(", ") || "none" },
    { name: "Explicit auth flows", holds: sameList(client.ExplicitAuthFlows, ["ALLOW_REFRESH_TOKEN_AUTH"]), expected: "ALLOW_REFRESH_TOKEN_AUTH", actual: asList(client.ExplicitAuthFlows).join(", ") || "none" },
    { name: "Allowed OAuth flows", holds: sameList(client.AllowedOAuthFlows, ["code"]), expected: "code", actual: asList(client.AllowedOAuthFlows).join(", ") || "none" },
    { name: "No client secret", holds: client.ClientSecret === undefined, expected: "no secret", actual: client.ClientSecret === undefined ? "no secret" : "a secret exists" },
    { name: "No pre-token-generation trigger", holds: preTokenTriggers.length === 0, expected: "none", actual: preTokenTriggers.join(", ") || "none" },
  ];
}

export function isGoogleOnly(evidence: FederationEvidence): boolean {
  return googleOnlyFindings(evidence).every((finding) => finding.holds);
}

export function callbackListAfterCliTask(deployed: string[], consoleOrigin: string, cliLoopbackPort: number): string[] {
  const added = [`http://127.0.0.1:${cliLoopbackPort}${CLI_CALLBACK_PATH}`, `${consoleOrigin}${CLI_CALLBACK_PATH}`];
  return [...deployed, ...added.filter((url) => !deployed.includes(url))];
}

function bulletList(values: string[]): string {
  return values.length === 0 ? "- none" : values.map((value) => `- ${value}`).join("\n");
}

function providerSummary(provider: Record<string, unknown>): { clientId: string; authorizeScopes: string; mapping: string } {
  const details = (provider.ProviderDetails ?? {}) as Record<string, string>;
  const mapping = (provider.AttributeMapping ?? {}) as Record<string, string>;
  return {
    clientId: details.client_id ?? "not reported",
    authorizeScopes: details.authorize_scopes ?? "not reported",
    mapping: Object.keys(mapping).sort().map((key) => `${key} <- ${mapping[key]}`).join("; ") || "none",
  };
}

export function renderPacket(description: SiteDescription, outputs: AmplifyOutputs, evidence: FederationEvidence): string {
  const { client, pool, provider } = evidence;
  const findings = googleOnlyFindings(evidence);
  const callbacks = asList(client.CallbackURLs);
  const logouts = asList(client.LogoutURLs);
  const afterCallbacks = callbackListAfterCliTask(callbacks, description.consoleOrigin, description.cliLoopbackPort);
  const providerFacts = providerSummary(provider);
  const units = (client.TokenValidityUnits ?? {}) as Record<string, string>;
  const validity = (label: string, value: unknown, unit: string | undefined) => `- ${label}: ${value ?? "default"} ${unit ?? ""}`.trimEnd();
  const verdict = findings.every((finding) => finding.holds) ? "Google-only: every check holds." : "NOT Google-only: at least one check fails; do not add the CLI callbacks.";
  const lines = [
    `# Federation review packet: ${description.site}`,
    "",
    `Registered with Prospectus: ${description.registered ? "yes (re-review)" : "no (first registration, kanbus-275596)"}`,
    `Client name: ${client.ClientName ?? "unknown"}`,
    `User pool: ${outputs.auth?.user_pool_id ?? "unknown"} (${outputs.auth?.aws_region ?? "unknown region"})`,
    `Federation client id: ${client.ClientId ?? outputs.custom?.prospectusSignIn?.clientId ?? "unknown"}`,
    "",
    "## 1. The synthesized client",
    "Source: `ProspectusGoogleOnlyClient` in `amplify/auth/prospectus-google-client.ts`. Cognito matches callback URLs exactly, so the CLI uses one fixed loopback port and one path.",
    "",
    "Callback URLs as deployed:",
    bulletList(callbacks),
    "",
    "Callback URLs after the CLI task:",
    bulletList(afterCallbacks),
    "",
    "Logout URLs as deployed (unchanged by the CLI task):",
    bulletList(logouts),
    "",
    "## 2. The Google identity provider and OAuth client",
    `- Provider name: ${provider.ProviderName ?? "unknown"} (type ${provider.ProviderType ?? "unknown"})`,
    `- Google OAuth client id: ${providerFacts.clientId}`,
    `- Authorize scopes: ${providerFacts.authorizeScopes}`,
    `- Attribute mapping: ${providerFacts.mapping}`,
    "- The Google client secret is never read into this packet.",
    "",
    "## 3. Sign-in is Google-only",
    ...findings.map((finding) => `- ${finding.holds ? "HOLDS" : "FAILS"}: ${finding.name} (expected ${finding.expected}; found ${finding.actual})`),
    "- No admin linking and no linked-profile flows: nothing under `amplify/auth/` links a Google login to another profile (`amplify/auth/resource.ts`), and Cognito password users are never created.",
    `- Verdict: ${verdict}`,
    "",
    "## 4. Code flow, scopes, PKCE, state and nonce",
    `- Allowed OAuth flows: ${asList(client.AllowedOAuthFlows).join(", ") || "none"}`,
    `- Allowed OAuth scopes: ${asList(client.AllowedOAuthScopes).join(", ") || "none"}`,
    "- PKCE S256: the CLI sends `code_challenge_method=S256` with a fresh verifier on every login (`cli_login` 0.3.0, `cli_login/oauth.py`, used by `src/papyrus_content/cli_user_auth.py`).",
    "- State: a fresh random value per login; the loopback receiver accepts the code only when the returned state matches exactly.",
    "- Nonce: taken from the Prospectus challenge by the enrollment task and required to equal the ID token nonce at resolve time.",
    "",
    "## 5. Token validity",
    validity("Access token", client.AccessTokenValidity, units.AccessToken),
    validity("ID token", client.IdTokenValidity, units.IdToken),
    validity("Refresh token", client.RefreshTokenValidity, units.RefreshToken),
    `- Prevent user existence errors: ${client.PreventUserExistenceErrors ?? "not reported"}`,
    `- Token revocation enabled: ${client.EnableTokenRevocation ?? "not reported"}`,
    `- Pool MFA configuration: ${pool.MfaConfiguration ?? "not reported"}`,
    "",
    "## 6. Origins",
    `- Site origin (and the broker's PAPYRUS_SITE_ORIGIN): ${description.siteOrigin}`,
    `- Console origin: ${description.consoleOrigin}`,
    `- Fixed CLI loopback port: ${description.cliLoopbackPort}`,
    "",
  ];
  return lines.join("\n");
}

function awsExecutable(): string {
  return process.env[AWS_EXECUTABLE_ENVIRONMENT_VARIABLE] ?? "aws";
}

function describe(profile: string, region: string, service: string[]): Record<string, unknown> {
  const output = execFileSync(awsExecutable(), [...service, "--region", region, "--profile", profile, "--output", "json"], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  return JSON.parse(output) as Record<string, unknown>;
}

export function readEvidence(description: SiteDescription, outputs: AmplifyOutputs): FederationEvidence {
  const userPoolId = outputs.auth?.user_pool_id;
  const clientId = outputs.custom?.prospectusSignIn?.clientId;
  const region = outputs.auth?.aws_region;
  if (!userPoolId || !clientId || !region) throw new Error(`${description.site}: amplify_outputs.json needs auth.user_pool_id, auth.aws_region and custom.prospectusSignIn.clientId.`);
  const clientDescription = describe(description.profile, region, ["cognito-idp", "describe-user-pool-client", "--user-pool-id", userPoolId, "--client-id", clientId]);
  const poolDescription = describe(description.profile, region, ["cognito-idp", "describe-user-pool", "--user-pool-id", userPoolId]);
  const providerDescription = describe(description.profile, region, ["cognito-idp", "describe-identity-provider", "--user-pool-id", userPoolId, "--provider-name", "Google"]);
  return {
    client: (clientDescription.UserPoolClient ?? {}) as Record<string, unknown>,
    pool: (poolDescription.UserPool ?? {}) as Record<string, unknown>,
    provider: (providerDescription.IdentityProvider ?? {}) as Record<string, unknown>,
  };
}

export function writePacket(description: SiteDescription, outputDirectory: string): { packetPath: string; googleOnly: boolean } {
  refuseRepositoryOutputDirectory(outputDirectory);
  const outputs = JSON.parse(readFileSync(description.outputsPath, "utf8")) as AmplifyOutputs;
  const evidence = readEvidence(description, outputs);
  mkdirSync(outputDirectory, { recursive: true });
  const packetPath = path.join(outputDirectory, `federation-packet-${description.site}.md`);
  writeFileSync(packetPath, renderPacket(description, outputs, evidence));
  return { packetPath, googleOnly: isGoogleOnly(evidence) };
}

export function renderIndex(rows: { site: string; registered: boolean; googleOnly: boolean }[]): string {
  const header = ["| Site | Registered | Google-only | Review needed |", "| --- | --- | --- | --- |"];
  const body = rows.map((row) => `| ${row.site} | ${row.registered ? "yes" : "no"} | ${row.googleOnly ? "yes" : "NO"} | ${row.googleOnly ? "yes: add CLI callbacks" : "yes: fix client first"} |`);
  return [...header, ...body, ""].join("\n");
}

function option(argumentsList: string[], name: string): string | undefined {
  const index = argumentsList.indexOf(name);
  return index === -1 ? undefined : argumentsList[index + 1];
}

function requiredOption(argumentsList: string[], name: string): string {
  const value = option(argumentsList, name);
  if (!value) throw new Error(`Missing ${name}.`);
  return value;
}

function descriptionFromArguments(argumentsList: string[]): SiteDescription {
  const siteOrigin = requiredOption(argumentsList, "--site-origin");
  return {
    site: requiredOption(argumentsList, "--site"),
    outputsPath: requiredOption(argumentsList, "--outputs"),
    profile: requiredOption(argumentsList, "--profile"),
    siteOrigin,
    consoleOrigin: option(argumentsList, "--console-origin") ?? siteOrigin,
    registered: argumentsList.includes("--registered"),
    cliLoopbackPort: Number(option(argumentsList, "--cli-port") ?? DEFAULT_CLI_LOOPBACK_PORT),
  };
}

function main(argumentsList: string[]): void {
  const outputDirectory = requiredOption(argumentsList, "--out-dir");
  if (argumentsList.includes("--all")) {
    const sites = JSON.parse(readFileSync(requiredOption(argumentsList, "--sites-file"), "utf8")) as SiteDescription[];
    const rows = sites.map((description) => ({ site: description.site, registered: description.registered, googleOnly: writePacket(description, outputDirectory).googleOnly }));
    const indexPath = path.join(outputDirectory, "federation-packet-index.md");
    writeFileSync(indexPath, renderIndex(rows));
    console.log(indexPath);
    return;
  }
  const result = writePacket(descriptionFromArguments(argumentsList), outputDirectory);
  console.log(result.packetPath);
  if (!result.googleOnly) {
    console.error("This site's client is NOT Google-only; see the packet.");
    process.exitCode = 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
