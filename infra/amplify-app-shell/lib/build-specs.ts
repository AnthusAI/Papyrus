import { AmplifyAppShellSiteConfig, hasCmsApp, resolveStoragePreviewPrefix } from "./site-config";

export type BuildSpecAppName = "cms-production" | "cms-staging" | "reader";

export function papyrusVersionToPep440(version: string): string {
  const match = /^(\d+\.\d+\.\d+)(?:-[0-9A-Za-z-]+\.(\d+))?$/.exec(version);
  if (!match) throw new Error(`cannot map ${version} to PEP 440`);
  return match[2] === undefined ? match[1] : `${match[1]}.dev${match[2]}`;
}

function yamlScalar(command: string): string {
  const needsQuoting = /: | #|^[-?:,\[\]{}#&*!|>'"%@`]|:$/.test(command);
  return needsQuoting ? `'${command.replace(/'/g, "''")}'` : command;
}

function commandLines(commands: string[], indent: string): string[] {
  return commands.map((command) => `${indent}- ${yamlScalar(command)}`);
}

const NPM_CLEAN_INSTALL = "npm ci --cache .npm --prefer-offline";

const FRONTEND_ENVIRONMENT_CAPTURE =
  "env | grep -e '^PAPYRUS_' -e '^SITE_ENV=' -e '^NEXT_PUBLIC_' >> .env.production";

const CHECKOUT_AS_PAPYRUS_ROOT = "PAPYRUS_ROOT=\"$PWD\"";

const RUNTIME_OUTPUTS_COPY = "cp amplify_outputs.json .next/amplify_outputs.json";

function pythonProvisioningCommands(config: AmplifyAppShellSiteConfig): string[] {
  return [
    "export UV_CACHE_DIR=\"$PWD/.uv-cache\"",
    "curl -LsSf https://astral.sh/uv/install.sh | sh",
    "export PATH=\"$HOME/.local/bin:$PATH\"",
    "uv python install 3.12",
    "uv venv --python 3.12 .venv",
    `uv pip install --python .venv "papyrus-newsroom[markus]==${papyrusVersionToPep440(config.papyrusVersion)}"`,
    "export PATH=\"$PWD/.venv/bin:$PATH\"",
  ];
}

function reader(config: AmplifyAppShellSiteConfig): NonNullable<AmplifyAppShellSiteConfig["reader"]> {
  if (!config.reader) throw new Error(`site ${config.siteId} has no reader app (frontend ${config.frontend})`);
  return config.reader;
}

function stagingPreviewFor(config: AmplifyAppShellSiteConfig): { buildCommand: string; baseDirectory: string } | undefined {
  return config.cms?.stagingPreview ?? config.reader;
}

function frontendSection(preBuildCommands: string[], buildCommands: string[], artifactsDirectory: string, cachePaths: string[]): string[] {
  const lines = ["frontend:", "  phases:"];
  if (preBuildCommands.length > 0) {
    lines.push("    preBuild:", "      commands:", ...commandLines(preBuildCommands, "        "));
  }
  lines.push(
    "    build:",
    "      commands:",
    ...commandLines(buildCommands, "        "),
    "  artifacts:",
    `    baseDirectory: ${artifactsDirectory}`,
    "    files:",
    "      - '**/*'",
    "  cache:",
    "    paths:",
    ...cachePaths.map((cachePath) => `      - ${cachePath}`),
  );
  return lines;
}

// After the backend deploy (it needs the skill function's ARN from amplify_outputs.json). It skips with one log line unless the site
// enables the alexa plugin and the shared developer credentials exist, and a failure is logged, never fatal: a site's deploy
// does not depend on Amazon. A Papyrus pin without the command prints usage and falls through the same way.
const ALEXA_SKILL_SYNC = "npx papyrus-app alexa-sync || echo \"alexa-sync did not complete; the site deploy continues\"";

const DEPLOY_STACK_IN_BUILD = "npx papyrus-infra deploy --site infra/site.json --only-branch main";

export function cmsProductionBuildSpec(config: AmplifyAppShellSiteConfig): string {
  const deployStackCommands = config.cms?.deployStackInBuild ? [DEPLOY_STACK_IN_BUILD] : [];
  return [
    "version: 1",
    "backend:",
    "  phases:",
    "    build:",
    "      commands:",
    ...commandLines(
      [
        NPM_CLEAN_INSTALL,
        ...deployStackCommands,
        "if [ -z \"${PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI:-}\" ]; then export PAPYRUS_CONSOLE_RESPONDER_ALLOW_LOCAL_BUILD=true; fi",
        "npx ampx pipeline-deploy --branch $AWS_BRANCH --app-id $AWS_APP_ID",
        ALEXA_SKILL_SYNC,
      ],
      "        ",
    ),
    ...frontendSection(
      [],
      [
        FRONTEND_ENVIRONMENT_CAPTURE,
        "npx papyrus-app sync && npm run build",
        ...(config.frontend === "pretext" ? [RUNTIME_OUTPUTS_COPY] : []),
      ],
      ".next",
      [".next/cache/**/*", ".npm/**/*"],
    ),
  ].join("\n") + "\n";
}

export function cmsStagingBuildSpec(config: AmplifyAppShellSiteConfig): string {
  const preBuild = [NPM_CLEAN_INSTALL, "npx ampx generate outputs --branch main --app-id $AWS_APP_ID"];
  const cachePaths = [".next/cache/**/*", ".npm/**/*"];
  const preview = config.frontend === "markus-static" ? stagingPreviewFor(config) : undefined;
  if (preview !== undefined) {
    preBuild.push(
      ...pythonProvisioningCommands(config),
      `${CHECKOUT_AS_PAPYRUS_ROOT} papyrus ops content export-published --drafts --out content-export --clean`,
      preview.buildCommand,
      `${CHECKOUT_AS_PAPYRUS_ROOT} papyrus ops content upload-preview --dir ${preview.baseDirectory} --prefix ${resolveStoragePreviewPrefix(config)}`,
    );
    cachePaths.push(".uv-cache/**/*");
  }
  return [
    "version: 1",
    ...frontendSection(
      preBuild,
      [
        FRONTEND_ENVIRONMENT_CAPTURE,
        "npx papyrus-app sync && npm run build",
        RUNTIME_OUTPUTS_COPY,
      ],
      ".next",
      cachePaths,
    ),
  ].join("\n") + "\n";
}

export function readerBuildSpec(config: AmplifyAppShellSiteConfig): string {
  const readerConfig = reader(config);
  return [
    "version: 1",
    ...frontendSection(
      [
        ...pythonProvisioningCommands(config),
        ...(readerConfig.preBuildCommands ?? []),
        ...(readerConfig.skipContentExport ? [] : ["papyrus ops content export-published --auth guest --out content-export --clean"]),
      ],
      [readerConfig.buildCommand],
      readerConfig.baseDirectory,
      [".uv-cache/**/*"],
    ),
  ].join("\n") + "\n";
}

export function buildSpecFor(config: AmplifyAppShellSiteConfig, app: BuildSpecAppName): string {
  if (app !== "reader" && !hasCmsApp(config)) throw new Error(`site ${config.siteId} has no cms app`);
  if (app === "cms-production") return cmsProductionBuildSpec(config);
  if (app === "cms-staging") return cmsStagingBuildSpec(config);
  return readerBuildSpec(config);
}
