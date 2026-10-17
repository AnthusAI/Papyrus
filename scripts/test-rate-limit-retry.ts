/**
 * Guest reader reads retry when Cognito throttles credential requests.
 *
 *   npx tsx scripts/test-rate-limit-retry.ts
 */
import { isRateLimitError, withRateLimitRetry } from "../lib/rate-limit-retry";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

async function main() {
  const throttled = Object.assign(new Error("Rate exceeded"), { name: "TooManyRequestsException" });
  const unauthorized = new Error(
    `GraphQL content request failed: [{"message":"Unauthorized","recoverySuggestion":"If you're calling an Amplify-generated API, make sure to set the \\"authMode\\" in generateClient({ authMode: '...' })"}]`,
  );
  assert(isRateLimitError(throttled), "a Cognito throttle is retryable");
  assert(isRateLimitError(unauthorized), "the Unauthorized that follows a failed credential fetch is retryable");
  assert(!isRateLimitError(new Error("No published GraphQL edition found")), "ordinary errors are not retryable");
  assert(!isRateLimitError(undefined), "non-errors are not retryable");

  const sleeps: number[] = [];
  const sleep = async (milliseconds: number) => { sleeps.push(milliseconds); };
  let calls = 0;
  const value = await withRateLimitRetry(async () => {
    calls += 1;
    if (calls < 3) throw throttled;
    return "ok";
  }, { sleep, random: () => 0.5 });
  assert(value === "ok" && calls === 3, "succeeds after two throttles");
  assert(sleeps.length === 2 && sleeps[1] === 2 * sleeps[0], "backoff doubles");

  calls = 0;
  let thrown: unknown;
  try {
    await withRateLimitRetry(async () => { calls += 1; throw new Error("boom"); }, { sleep });
  } catch (error) {
    thrown = error;
  }
  assert(calls === 1 && thrown instanceof Error, "a non-throttle error is thrown at once");

  calls = 0;
  try {
    await withRateLimitRetry(async () => { calls += 1; throw throttled; }, { attempts: 3, sleep });
  } catch (error) {
    thrown = error;
  }
  assert(calls === 3 && thrown === throttled, "gives up after the attempt limit with the original error");

  console.log("PASS: rate limit retry");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
