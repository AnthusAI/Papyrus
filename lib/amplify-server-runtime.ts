import fs from "node:fs";
import { createServerRunner } from "@aws-amplify/adapter-nextjs";
import { Amplify, type ResourcesConfig } from "aws-amplify";
import { assertSandboxAmplifyOutputsForDev } from "./amplify-outputs-guard";
import { getAmplifyOutputsPath } from "./amplify-outputs-path";

type AmplifyServerRuntime = ReturnType<typeof createServerRunner> & {
  config: ResourcesConfig;
};

let cachedRuntime: AmplifyServerRuntime | null = null;

export function getAmplifyServerRuntime(): AmplifyServerRuntime {
  if (cachedRuntime) return cachedRuntime;

  const config = loadAmplifyOutputs();
  Amplify.configure(config, { ssr: true });
  cachedRuntime = {
    ...createServerRunner({ config }),
    config,
  };
  return cachedRuntime;
}

export function hasAmplifyOutputs(): boolean {
  return fs.existsSync(getAmplifyOutputsPath());
}

function loadAmplifyOutputs(): ResourcesConfig {
  const outputsPath = getAmplifyOutputsPath();
  if (!fs.existsSync(outputsPath)) {
    throw new Error(
      "Papyrus requires amplify_outputs.json for GraphQL content. Run `npm run outputs:sandbox` or `npm run sandbox` first.",
    );
  }

  const raw = JSON.parse(fs.readFileSync(outputsPath, "utf8")) as ResourcesConfig & {
    auth?: { identity_pool_id?: string; user_pool_client_id?: string; user_pool_id?: string };
  };
  assertSandboxAmplifyOutputsForDev(raw as Record<string, unknown>);

  // Reader SSR uses Cognito identity-pool guest credentials (no expiring AppSync API keys).
  const cognito = (raw as { Auth?: { Cognito?: Record<string, unknown> } }).Auth?.Cognito ?? {};
  const legacyAuth = raw.auth;
  return {
    ...raw,
    Auth: {
      Cognito: {
        ...cognito,
        identityPoolId:
          (cognito.identityPoolId as string | undefined)
          ?? legacyAuth?.identity_pool_id,
        userPoolClientId:
          (cognito.userPoolClientId as string | undefined)
          ?? legacyAuth?.user_pool_client_id,
        userPoolId:
          (cognito.userPoolId as string | undefined)
          ?? legacyAuth?.user_pool_id,
        allowGuestAccess: true,
      },
    },
  } as ResourcesConfig;
}
