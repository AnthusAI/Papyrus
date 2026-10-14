import fs from "node:fs";
import { createServerRunner } from "@aws-amplify/adapter-nextjs";
import { Amplify, type ResourcesConfig } from "aws-amplify";
import {
  createAWSCredentialsAndIdentityIdProvider,
  createUserPoolsTokenProvider,
  runWithAmplifyServerContext as runWithAmplifyContext,
} from "aws-amplify/adapter-core";
import { sharedInMemoryStorage } from "aws-amplify/utils";
import { createSharedCredentialsProvider } from "./shared-credentials-provider";
import { assertSandboxAmplifyOutputsForDev } from "./amplify-outputs-guard";
import { getAmplifyOutputsPath } from "./amplify-outputs-path";

type AmplifyServerRuntime = ReturnType<typeof createServerRunner> & {
  config: ResourcesConfig;
};

let cachedRuntime: AmplifyServerRuntime | null = null;

export function getAmplifyServerRuntime(): AmplifyServerRuntime {
  if (cachedRuntime) return cachedRuntime;

  const config = loadAmplifyOutputs();
  cachedRuntime = {
    ...createServerRunner({ config }),
    config,
  };
  Amplify.configure(config, config.Auth ? { ssr: true, Auth: getGuestProviders(config) } : { ssr: true });
  return cachedRuntime;
}

type GuestProviders = {
  credentialsProvider: ReturnType<typeof createAWSCredentialsAndIdentityIdProvider>;
  tokenProvider: ReturnType<typeof createUserPoolsTokenProvider>;
};

const GUEST_PROVIDERS_KEY = Symbol.for("papyrus.guestAmplifyProviders");

function getGuestProviders(config: ResourcesConfig): GuestProviders {
  const holder = globalThis as unknown as Record<symbol, GuestProviders | undefined>;
  const existing = holder[GUEST_PROVIDERS_KEY];
  if (existing) return existing;
  const auth = config.Auth as NonNullable<ResourcesConfig["Auth"]>;
  const created: GuestProviders = {
    credentialsProvider: createSharedCredentialsProvider(
      createAWSCredentialsAndIdentityIdProvider(auth, sharedInMemoryStorage),
    ),
    tokenProvider: createUserPoolsTokenProvider(auth, sharedInMemoryStorage),
  };
  holder[GUEST_PROVIDERS_KEY] = created;
  return created;
}

export function runWithGuestAmplifyContext<T>(operation: (contextSpec: Parameters<Parameters<typeof runWithAmplifyContext>[2]>[0]) => Promise<T>): Promise<T> {
  const { config } = getAmplifyServerRuntime();
  if (!config.Auth) return runWithAmplifyContext(config, {}, operation) as Promise<T>;
  return runWithAmplifyContext(config, { Auth: getGuestProviders(config) }, operation) as Promise<T>;
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
