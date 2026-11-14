import { SHARED_TIERS, type SharedTier } from "./names";

/**
 * The numbers the shared stacks need. They live here, in one reviewed file, and never in a template or an aspect (the standing rule
 * against arbitrary limits). A tier with `null` has not been measured yet and cannot be synthesised.
 */
export type SharedStackSettings = {
  reservedConcurrency: { perFunction: number; overrides: Record<string, number>; tierLimit: number };
  alarms: {
    periodMinutes: number;
    functionErrors: number;
    functionThrottles: number;
    /** An alarm fires when a function's concurrency reaches this share of its reserved concurrency. */
    concurrencyShareOfReserved: number;
    appSyncServerErrors: number;
    appSyncClientErrors: number;
    dynamoDbThrottledRequests: number;
    projectionDeadLetterMessages: number;
    /** Paths a stack's edge purges in a week before the alarm fires. */
    purgedPathsPerWeek: number;
  };
  logRetentionDays: number;
};

type SettingsFile = { tiers: Record<SharedTier, SharedStackSettings | null> };

/**
 * The settings of each shared stack (PPY-daf673, PPY-f40a02).
 *
 * - The staging values are a documented starting point so the first create can happen; they MUST be replaced from staging traffic
 *   (measured peak concurrent executions per function, alarm history) before shared production is created.
 * - Production has no values on purpose: its synthesis refuses until the reserved concurrency, the tier limit and the alarm
 *   thresholds are set from staging traffic.
 * - `perFunction` is the reserved concurrency of every function the stack owns; `overrides` sets one function (the key is the
 *   function's construct id). `tierLimit` is the most the stack may reserve in total, so unreserved headroom stays with the
 *   dedicated sites (AWS also requires 100 unreserved).
 */
export const SHARED_STACK_SETTINGS: SettingsFile = {
  tiers: {
    staging: {
      reservedConcurrency: { perFunction: 2, overrides: {}, tierLimit: 120 },
      alarms: {
        periodMinutes: 5,
        functionErrors: 1,
        functionThrottles: 1,
        concurrencyShareOfReserved: 0.8,
        appSyncServerErrors: 1,
        appSyncClientErrors: 50,
        dynamoDbThrottledRequests: 1,
        projectionDeadLetterMessages: 1,
        purgedPathsPerWeek: 25,
      },
      logRetentionDays: 30,
    },
    production: null,
  },
};

const POSITIVE_INTEGER_FIELDS = [
  ["reservedConcurrency", "perFunction"],
  ["reservedConcurrency", "tierLimit"],
  ["alarms", "periodMinutes"],
  ["alarms", "functionErrors"],
  ["alarms", "functionThrottles"],
  ["alarms", "appSyncServerErrors"],
  ["alarms", "appSyncClientErrors"],
  ["alarms", "dynamoDbThrottledRequests"],
  ["alarms", "projectionDeadLetterMessages"],
  ["alarms", "purgedPathsPerWeek"],
] as const;

/** Refuses a missing or malformed value naming the setting, so a bad number never reaches a template. */
export function validateSharedStackSettings(tier: SharedTier, value: SharedStackSettings | null | undefined): SharedStackSettings {
  if (value === null || value === undefined) {
    throw new Error(
      `The ${tier} shared stack has no settings in amplify/shared-stack/settings.ts: its reserved concurrency (PPY-f40a02), tier limit and alarm thresholds must be set from staging traffic before it can be synthesised.`,
    );
  }
  for (const [group, field] of POSITIVE_INTEGER_FIELDS) {
    const number = (value as unknown as Record<string, Record<string, unknown>>)[group]?.[field];
    if (!Number.isInteger(number) || (number as number) < 1) throw new Error(`Shared ${tier} settings: ${group}.${field} must be a positive integer.`);
  }
  const share = value.alarms.concurrencyShareOfReserved;
  if (typeof share !== "number" || !(share > 0 && share <= 1)) throw new Error(`Shared ${tier} settings: alarms.concurrencyShareOfReserved must be above 0 and at most 1.`);
  if (!Number.isInteger(value.logRetentionDays) || value.logRetentionDays < 1) throw new Error(`Shared ${tier} settings: logRetentionDays must be a positive integer.`);
  for (const [name, number] of Object.entries(value.reservedConcurrency.overrides ?? {})) {
    if (!Number.isInteger(number) || number < 1) throw new Error(`Shared ${tier} settings: reservedConcurrency.overrides.${name} must be a positive integer.`);
  }
  return value;
}

export function sharedStackSettings(tier: SharedTier, file: SettingsFile = SHARED_STACK_SETTINGS): SharedStackSettings {
  if (!SHARED_TIERS.includes(tier)) throw new Error(`Unknown shared tier ${JSON.stringify(tier)}.`);
  return validateSharedStackSettings(tier, file.tiers[tier]);
}
