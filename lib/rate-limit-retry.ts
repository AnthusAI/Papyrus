export const RATE_LIMIT_RETRY_ATTEMPTS = 6;
export const RATE_LIMIT_RETRY_BASE_MILLISECONDS = 300;

export function isRateLimitError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const { name, message } = error as { name?: unknown; message?: unknown };
  const text = `${typeof name === "string" ? name : ""} ${typeof message === "string" ? message : ""}`;
  return /TooManyRequests|ThrottlingException|Rate exceeded|Unauthorized[\s\S]*set the \\?"authMode\\?"/i.test(text);
}

export async function withRateLimitRetry<T>(
  operation: () => Promise<T>,
  options: { attempts?: number; baseMilliseconds?: number; sleep?: (milliseconds: number) => Promise<void>; random?: () => number } = {},
): Promise<T> {
  const attempts = options.attempts ?? RATE_LIMIT_RETRY_ATTEMPTS;
  const baseMilliseconds = options.baseMilliseconds ?? RATE_LIMIT_RETRY_BASE_MILLISECONDS;
  const sleep = options.sleep ?? ((milliseconds: number) => new Promise<void>((resolve) => setTimeout(resolve, milliseconds)));
  const random = options.random ?? Math.random;
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      if (attempt >= attempts || !isRateLimitError(error)) throw error;
      await sleep(baseMilliseconds * 2 ** (attempt - 1) * (0.5 + random()));
    }
  }
}
