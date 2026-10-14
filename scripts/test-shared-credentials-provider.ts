/**
 * One shared guest credential provider: single-flight, cached until near expiry, jittered backoff.
 *
 *   npx tsx scripts/test-shared-credentials-provider.ts
 */
import { createSharedCredentialsProvider } from "../lib/shared-credentials-provider";
import { fullJitterDelayMilliseconds, withRateLimitRetry } from "../lib/rate-limit-retry";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

const throttled = () => Object.assign(new Error("Rate exceeded"), { name: "TooManyRequestsException" });
type Result = { credentials: { expiration?: Date }; identityId: string };

function fakeProvider(failuresBeforeSuccess: number, lifetimeMilliseconds: number, clock: { now: number }) {
  const state: { calls: number; clears: number } = { calls: 0, clears: 0 };
  return {
    state,
    provider: {
      async getCredentialsAndIdentityId(_options: { forceRefresh?: boolean }): Promise<Result> {
        state.calls += 1;
        await Promise.resolve();
        if (state.calls <= failuresBeforeSuccess) throw throttled();
        return { credentials: { expiration: new Date(clock.now + lifetimeMilliseconds) }, identityId: `id-${state.calls}` };
      },
      clearCredentialsAndIdentityId() {
        state.clears += 1;
      },
    },
  };
}

async function main() {
  const clock = { now: 1_000_000 };
  const sleeps: number[] = [];
  const retry = { sleep: async (milliseconds: number) => { sleeps.push(milliseconds); }, random: () => 0.5 };

  const healthy = fakeProvider(0, 60 * 60 * 1000, clock);
  const shared = createSharedCredentialsProvider(healthy.provider, { now: () => clock.now, retry });
  const burst = await Promise.all(Array.from({ length: 50 }, () => shared.getCredentialsAndIdentityId({})));
  assert(healthy.state.calls === 1, `50 concurrent callers share one upstream request, got ${healthy.state.calls}`);
  assert(burst.every((entry) => entry === burst[0]), "every caller receives the same result");
  await shared.getCredentialsAndIdentityId({});
  assert(healthy.state.calls === 1, "later callers hit the cache");

  clock.now += 56 * 60 * 1000;
  await shared.getCredentialsAndIdentityId({});
  assert(healthy.state.calls === 2, "credentials within five minutes of expiry are refreshed");
  await shared.getCredentialsAndIdentityId({ forceRefresh: true });
  assert(healthy.state.calls === 3, "forceRefresh bypasses the cache");
  shared.clearCredentialsAndIdentityId();
  assert(healthy.state.clears === 1, "clear reaches the inner provider");
  await shared.getCredentialsAndIdentityId({});
  assert(healthy.state.calls === 4, "cache is empty after clear");

  const flaky = fakeProvider(4, 60 * 60 * 1000, clock);
  const flakyShared = createSharedCredentialsProvider(flaky.provider, { now: () => clock.now, retry });
  sleeps.length = 0;
  await Promise.all(Array.from({ length: 20 }, () => flakyShared.getCredentialsAndIdentityId({})));
  assert(flaky.state.calls === 5, `4 throttles then success is 5 upstream calls for 20 callers, got ${flaky.state.calls}`);
  assert(sleeps.length === 4, "one backoff sleep per throttle");

  const alwaysThrottled = fakeProvider(Number.MAX_SAFE_INTEGER, 1000, clock);
  const hopeless = createSharedCredentialsProvider(alwaysThrottled.provider, { now: () => clock.now, retry: { ...retry, attempts: 5 } });
  let thrown: unknown;
  try { await hopeless.getCredentialsAndIdentityId({}); } catch (error) { thrown = error; }
  assert(thrown instanceof Error && thrown.name === "TooManyRequestsException", "original error surfaces after the attempts");
  assert(alwaysThrottled.state.calls === 5, "attempts are bounded");
  try { await hopeless.getCredentialsAndIdentityId({}); } catch { /* expected */ }
  assert(alwaysThrottled.state.calls === 10, "a failed flight does not stay cached");

  for (let attempt = 1; attempt <= 12; attempt += 1) {
    const ceiling = Math.min(20_000, 500 * 2 ** (attempt - 1));
    assert(fullJitterDelayMilliseconds(attempt, 500, 20_000, () => 0) === 0, "full jitter can be zero");
    assert(fullJitterDelayMilliseconds(attempt, 500, 20_000, () => 0.999999) < ceiling, `attempt ${attempt} stays under ${ceiling}`);
    assert(fullJitterDelayMilliseconds(attempt, 500, 20_000, () => 1) === ceiling, "ceiling is exponential then capped");
  }

  let virtualNow = 0;
  let calls = 0;
  const budgetError = throttled();
  let budgetThrown: unknown;
  try {
    await withRateLimitRetry(async () => { calls += 1; throw budgetError; }, {
      attempts: 1000,
      random: () => 1,
      now: () => virtualNow,
      sleep: async (milliseconds) => { virtualNow += milliseconds; },
    });
  } catch (error) { budgetThrown = error; }
  assert(budgetThrown === budgetError, "the original error surfaces when the budget is spent");
  assert(virtualNow <= 120_000 && virtualNow > 90_000 && calls > 5, `total waiting stays inside the two minute budget (${virtualNow} ms, ${calls} calls)`);

  console.log("PASS: shared credentials provider");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
