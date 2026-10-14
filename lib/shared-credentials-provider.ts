import { withRateLimitRetry, type RateLimitRetryOptions } from "./rate-limit-retry";

export const CREDENTIAL_EXPIRY_SAFETY_MILLISECONDS = 5 * 60 * 1000;

export type CredentialsAndIdentityIdLike = {
  credentials: { expiration?: Date };
};

export type CredentialsProviderLike<Options, Result extends CredentialsAndIdentityIdLike> = {
  getCredentialsAndIdentityId(options: Options): Promise<Result | undefined>;
  clearCredentialsAndIdentityId(): void;
};

export type SharedCredentialsProviderOptions = {
  retry?: RateLimitRetryOptions;
  expirySafetyMilliseconds?: number;
  now?: () => number;
};

export function createSharedCredentialsProvider<
  Options extends { forceRefresh?: boolean },
  Result extends CredentialsAndIdentityIdLike,
>(
  inner: CredentialsProviderLike<Options, Result>,
  settings: SharedCredentialsProviderOptions = {},
): CredentialsProviderLike<Options, Result> {
  const now = settings.now ?? Date.now;
  const safety = settings.expirySafetyMilliseconds ?? CREDENTIAL_EXPIRY_SAFETY_MILLISECONDS;
  let cached: Result | undefined;
  let inflight: Promise<Result | undefined> | undefined;

  const isFresh = (value: Result | undefined): value is Result => {
    if (!value) return false;
    const expiration = value.credentials.expiration;
    return !expiration || expiration.getTime() - safety > now();
  };

  return {
    async getCredentialsAndIdentityId(options) {
      if (!options?.forceRefresh && isFresh(cached)) return cached;
      if (inflight) return inflight;
      const request = withRateLimitRetry(() => inner.getCredentialsAndIdentityId(options), {
        now,
        ...settings.retry,
      })
        .then((result) => {
          cached = result;
          return result;
        })
        .finally(() => {
          inflight = undefined;
        });
      inflight = request;
      return request;
    },
    clearCredentialsAndIdentityId() {
      cached = undefined;
      inner.clearCredentialsAndIdentityId();
    },
  };
}
