export const RATE_LIMIT_RETRY_ATTEMPTS = 14;
export const RATE_LIMIT_RETRY_BASE_MILLISECONDS = 500;
export const RATE_LIMIT_RETRY_CAP_MILLISECONDS = 20_000;
export const RATE_LIMIT_RETRY_BUDGET_MILLISECONDS = 120_000;

export function isRateLimitError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const { name, message } = error as { name?: unknown; message?: unknown };
  const text = `${typeof name === "string" ? name : ""} ${typeof message === "string" ? message : ""}`;
  return /TooManyRequests|ThrottlingException|Rate exceeded|Unauthorized[\s\S]*set the \\?"authMode\\?"/i.test(text);
}

export type RateLimitRetryOptions = {
  attempts?: number;
  baseMilliseconds?: number;
  capMilliseconds?: number;
  budgetMilliseconds?: number;
  sleep?: (milliseconds: number) => Promise<void>;
  random?: () => number;
  now?: () => number;
};

export function fullJitterDelayMilliseconds(
  attempt: number,
  baseMilliseconds: number,
  capMilliseconds: number,
  random: () => number,
): number {
  const ceiling = Math.min(capMilliseconds, baseMilliseconds * 2 ** (attempt - 1));
  return random() * ceiling;
}

export async function withRateLimitRetry<T>(
  operation: () => Promise<T>,
  options: RateLimitRetryOptions = {},
): Promise<T> {
  const attempts = options.attempts ?? RATE_LIMIT_RETRY_ATTEMPTS;
  const baseMilliseconds = options.baseMilliseconds ?? RATE_LIMIT_RETRY_BASE_MILLISECONDS;
  const capMilliseconds = options.capMilliseconds ?? RATE_LIMIT_RETRY_CAP_MILLISECONDS;
  const budgetMilliseconds = options.budgetMilliseconds ?? RATE_LIMIT_RETRY_BUDGET_MILLISECONDS;
  const sleep = options.sleep ?? ((milliseconds: number) => new Promise<void>((resolve) => setTimeout(resolve, milliseconds)));
  const random = options.random ?? Math.random;
  const now = options.now ?? Date.now;
  const startedAt = now();
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      if (attempt >= attempts || !isRateLimitError(error)) throw error;
      const delay = fullJitterDelayMilliseconds(attempt, baseMilliseconds, capMilliseconds, random);
      if (now() - startedAt + delay > budgetMilliseconds) throw error;
      await sleep(delay);
    }
  }
}
