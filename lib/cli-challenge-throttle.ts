/**
 * The site's own limit on `/cli/challenge`, because central Prospectus has no per-site limit and the route is public.
 *
 * A token bucket shared by every caller of the site: it refills `ratePerSecond` tokens each second up to `burst`.
 * The defaults, 1 per second with a burst of 2, are what Prospectus's own CRM uses for the same route, and they sit far
 * above real demand: a challenge is issued once per login that a person then approves in a browser. Both are
 * configurable per site with PAPYRUS_CLI_CHALLENGE_RATE_PER_SECOND and PAPYRUS_CLI_CHALLENGE_BURST. The bucket is one
 * item in a DynamoDB table, updated with a conditional write so concurrent compute instances cannot overspend it.
 * Any storage failure refuses the request (fail closed).
 */
export const DEFAULT_CHALLENGE_RATE_PER_SECOND = 1;
export const DEFAULT_CHALLENGE_BURST = 2;
const MILLI = 1000;
const ATTEMPTS = 4;

export interface ThrottleState {
  millitokens: number;
  updatedAtMilliseconds: number;
}

export interface ThrottleStore {
  read(): Promise<ThrottleState | null>;
  /** Writes `next` only if the stored state is still `previous` (null: still absent). Returns whether it wrote. */
  writeIfUnchanged(previous: ThrottleState | null, next: ThrottleState): Promise<boolean>;
}

export interface ThrottleLimits {
  ratePerSecond: number;
  burst: number;
}

export function throttleLimitsFromEnvironment(environment: Record<string, string | undefined> = process.env): ThrottleLimits {
  const positive = (value: string | undefined, fallback: number) => {
    const parsed = Number(value);
    return value !== undefined && value.trim() !== "" && Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };
  return {
    ratePerSecond: positive(environment.PAPYRUS_CLI_CHALLENGE_RATE_PER_SECOND, DEFAULT_CHALLENGE_RATE_PER_SECOND),
    burst: Math.max(1, Math.floor(positive(environment.PAPYRUS_CLI_CHALLENGE_BURST, DEFAULT_CHALLENGE_BURST))),
  };
}

/** Takes one token. Returns false when the bucket is empty or could not be updated. */
export async function takeChallengeToken(store: ThrottleStore, limits: ThrottleLimits, nowMilliseconds: number = Date.now()): Promise<boolean> {
  const capacity = limits.burst * MILLI;
  for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
    const previous = await store.read();
    const elapsed = previous ? Math.max(0, nowMilliseconds - previous.updatedAtMilliseconds) : 0;
    const available = previous ? Math.min(capacity, previous.millitokens + Math.floor(elapsed * limits.ratePerSecond)) : capacity;
    if (available < MILLI) return false;
    if (await store.writeIfUnchanged(previous, { millitokens: available - MILLI, updatedAtMilliseconds: nowMilliseconds })) return true;
  }
  return false;
}

export function dynamoThrottleStore(tableName: string, client?: { send: (command: unknown) => Promise<any> }): ThrottleStore {
  const key = { pk: { S: "cli-challenge" } };
  const commands = async () => import("@aws-sdk/client-dynamodb");
  const sender = async () => client ?? new (await commands()).DynamoDBClient({});
  return {
    async read() {
      const { GetItemCommand } = await commands();
      const answer = await (await sender()).send(new GetItemCommand({ TableName: tableName, Key: key, ConsistentRead: true }));
      if (!answer.Item) return null;
      return { millitokens: Number(answer.Item.millitokens?.N), updatedAtMilliseconds: Number(answer.Item.updatedAtMilliseconds?.N) };
    },
    async writeIfUnchanged(previous, next) {
      const { PutItemCommand } = await commands();
      try {
        await (await sender()).send(new PutItemCommand({
          TableName: tableName,
          Item: {
            ...key,
            millitokens: { N: String(next.millitokens) },
            updatedAtMilliseconds: { N: String(next.updatedAtMilliseconds) },
            expiresAt: { N: String(Math.floor(next.updatedAtMilliseconds / 1000) + 3600) },
          },
          ...(previous
            ? { ConditionExpression: "updatedAtMilliseconds = :previous", ExpressionAttributeValues: { ":previous": { N: String(previous.updatedAtMilliseconds) } } }
            : { ConditionExpression: "attribute_not_exists(pk)" }),
        }));
        return true;
      } catch (error) {
        if ((error as { name?: string }).name === "ConditionalCheckFailedException") return false;
        throw error;
      }
    },
  };
}
