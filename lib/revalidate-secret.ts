import { timingSafeEqual } from "node:crypto";
import { GetParameterCommand, SSMClient } from "@aws-sdk/client-ssm";

export const REVALIDATE_SECRET_PARAMETER_ENV = "PAPYRUS_REVALIDATE_SECRET_PARAMETER";
export const REVALIDATE_SECRET_CACHE_MILLISECONDS = 5 * 60 * 1000;

export type RevalidateSecretReader = (parameterName: string) => Promise<string | null>;

type CachedSecret = { parameterName: string; value: string; expiresAt: number };

let cachedSecret: CachedSecret | null = null;
let defaultSsmClient: SSMClient | null = null;

export function resetRevalidateSecretCache(): void {
  cachedSecret = null;
}

async function readSecretFromSsm(parameterName: string): Promise<string | null> {
  defaultSsmClient ??= new SSMClient({});
  const response = await defaultSsmClient.send(new GetParameterCommand({ Name: parameterName, WithDecryption: true }));
  const value = response.Parameter?.Value?.trim();
  return value ? value : null;
}

export async function loadRevalidateSecret(
  options: { environment?: Record<string, string | undefined>; readSecret?: RevalidateSecretReader; now?: number } = {},
): Promise<string | null> {
  const environment = options.environment ?? process.env;
  const parameterName = environment[REVALIDATE_SECRET_PARAMETER_ENV]?.trim();
  if (!parameterName) return null;
  const now = options.now ?? Date.now();
  if (cachedSecret && cachedSecret.parameterName === parameterName && cachedSecret.expiresAt > now) {
    return cachedSecret.value;
  }
  try {
    const value = (await (options.readSecret ?? readSecretFromSsm)(parameterName))?.trim();
    if (!value) return null;
    cachedSecret = { parameterName, value, expiresAt: now + REVALIDATE_SECRET_CACHE_MILLISECONDS };
    return value;
  } catch (error) {
    console.error(`Revalidate secret parameter could not be read (${error instanceof Error ? error.name : "error"}).`);
    return null;
  }
}

export function secretsMatch(provided: string | null | undefined, expected: string): boolean {
  const providedBytes = Buffer.from((provided ?? "").trim());
  const expectedBytes = Buffer.from(expected);
  return providedBytes.length === expectedBytes.length && timingSafeEqual(providedBytes, expectedBytes);
}

export async function isAuthorizedRevalidateRequest(
  providedSecret: string | null | undefined,
  options: Parameters<typeof loadRevalidateSecret>[0] = {},
): Promise<boolean> {
  const expected = await loadRevalidateSecret(options);
  if (!expected) return false;
  return secretsMatch(providedSecret, expected);
}
