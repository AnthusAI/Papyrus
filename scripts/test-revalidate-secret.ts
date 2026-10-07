/**
 * Revalidation secret handling: read from the SSM parameter named by the
 * environment, fail closed, constant-time compare, no env-var secret.
 *
 *   npx tsx scripts/test-revalidate-secret.ts
 */
import { readFileSync } from "node:fs";
import {
  REVALIDATE_SECRET_CACHE_MILLISECONDS,
  REVALIDATE_SECRET_PARAMETER_ENV,
  isAuthorizedRevalidateRequest,
  loadRevalidateSecret,
  resetRevalidateSecretCache,
  secretsMatch,
} from "../lib/revalidate-secret";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) throw new Error(`FAIL: ${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

async function main() {
  const environment = { [REVALIDATE_SECRET_PARAMETER_ENV]: "/papyrus/demo/revalidate-secret" };
  let reads = 0;
  const readSecret = async (name: string) => {
    reads += 1;
    return name === "/papyrus/demo/revalidate-secret" ? "  s3cret-value \n" : null;
  };

  assertEqual(secretsMatch("abc", "abc"), true, "equal secrets match");
  assertEqual(secretsMatch(" abc ", "abc"), true, "header is trimmed");
  assertEqual(secretsMatch("abd", "abc"), false, "different secrets differ");
  assertEqual(secretsMatch("abcd", "abc"), false, "different lengths differ");
  assertEqual(secretsMatch(null, "abc"), false, "missing header fails");

  resetRevalidateSecretCache();
  assertEqual(await isAuthorizedRevalidateRequest("s3cret-value", { environment, readSecret }), true, "correct secret authorized");
  assertEqual(await isAuthorizedRevalidateRequest("wrong", { environment, readSecret }), false, "wrong secret rejected");
  assertEqual(await isAuthorizedRevalidateRequest(null, { environment, readSecret }), false, "missing secret rejected");
  assertEqual(reads, 1, "secret is cached between requests");

  await loadRevalidateSecret({ environment, readSecret, now: Date.now() + REVALIDATE_SECRET_CACHE_MILLISECONDS + 1000 });
  assertEqual(reads, 2, "secret is re-read after the cache expires");

  resetRevalidateSecretCache();
  assertEqual(await isAuthorizedRevalidateRequest("anything", { environment: {}, readSecret }), false, "no parameter configured fails closed");
  assertEqual(
    await isAuthorizedRevalidateRequest("anything", { environment: { PAPYRUS_REVALIDATE_SECRET: "anything" }, readSecret }),
    false,
    "a PAPYRUS_REVALIDATE_SECRET variable is not a secret source",
  );
  const failingRead = async () => {
    throw new Error("AccessDeniedException secret-in-message");
  };
  const originalError = console.error;
  const logged: string[] = [];
  console.error = (...parts: unknown[]) => void logged.push(parts.join(" "));
  try {
    assertEqual(await isAuthorizedRevalidateRequest("anything", { environment, readSecret: failingRead }), false, "read failure fails closed");
  } finally {
    console.error = originalError;
  }
  assertEqual(logged.some((line) => line.includes("secret-in-message")), false, "error detail is not logged");
  assertEqual(await isAuthorizedRevalidateRequest("anything", { environment, readSecret: async () => "  " }), false, "empty parameter fails closed");

  const routeSource = readFileSync(new URL("../app/api/revalidate/route.ts", import.meta.url), "utf8");
  assertEqual(routeSource.includes("process.env.PAPYRUS_REVALIDATE_SECRET"), false, "route does not read a secret env var");
  assertEqual(routeSource.includes("isAuthorizedRevalidateRequest"), true, "route verifies through the secret helper");

  console.log("revalidate secret tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
