import type { PluginRequest } from "../types";

export const READER_DIMENSION_NAME = /^[a-z][a-z0-9-]{0,23}$/;
export const RESERVED_DIMENSIONS = ["up", "used-it"];
export const READER_HANDLE_NAME = /^[a-z0-9_-]{3,24}$/;
export const COMPUTE_ROLE_ARN = /^arn:aws:iam::[0-9]{12}:role\/[A-Za-z0-9+=,.@_/-]{1,512}$/;

export type ReaderSteeringConfig = {
  /** The IAM role of the CMS app's server runtime (the `CmsComputeRoleArn` output of the app-shell stack): the only caller of reader-actions. */
  computeRoleArn: string;
  /** Rating dimensions of the publication, such as `real` and `useful`. `up` and `used-it` are always available. */
  dimensions: string[];
  limits: {
    /** Votes and ratings one reader may make in a clock hour. */
    actionsPerHour: number;
    /** Readers whose profile is younger than this many hours get `actionsPerHour / newAccountDivisor`. */
    newAccountHours: number;
    newAccountDivisor: number;
  };
  /** Handles nobody may take, on top of the built-in list. Lowercase. */
  reservedHandles: string[];
  karma: { upvoteWeight: number; usedItWeight: number };
  ranking: {
    /** Front: the editor composite loses half its weight every this many hours. */
    halfLifeHours: number;
    /** Rising counts upvotes in this window. */
    risingWindowHours: number;
    /** Reader ratings per item needed before the reader composite counts in Front. */
    readerMinimum: number;
    /** Weight of the editor composite in Front once readers have rated (the reader composite gets the rest). */
    editorWeight: number;
  };
  snapshot: {
    /** An EventBridge rule runs the snapshot every `intervalHours`. Off by default. */
    schedule: boolean;
    intervalHours: number;
    /** A hype gap needs at least this many ratings on every dimension involved. */
    hypeMinimum: number;
  };
  /**
   * Poll Prospectus for retired reader subjects in each scheduled snapshot run (requires `snapshot.schedule`, and a site
   * whose app-shell sets `cms.readerRetirementPoll`). Off by default.
   */
  retirementPoll: boolean;
};

const KNOWN_KEYS = new Set(["name", "computeRoleArn", "dimensions", "limits", "reservedHandles", "karma", "ranking", "snapshot", "retirementPoll"]);

function object(raw: unknown, label: string, known: string[]): Record<string, unknown> {
  if (raw === undefined) return {};
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) throw new Error(`reader-steering plugin ${label} must be an object`);
  const unknown = Object.keys(raw).filter((key) => !known.includes(key));
  if (unknown.length > 0) throw new Error(`Unknown reader-steering plugin ${label} settings: ${unknown.join(", ")}`);
  return raw as Record<string, unknown>;
}

function integer(raw: unknown, label: string, fallback: number, minimum: number, maximum: number): number {
  const value = raw === undefined ? fallback : raw;
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new Error(`reader-steering plugin ${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value as number;
}

function number(raw: unknown, label: string, fallback: number, minimum: number, maximum: number): number {
  const value = raw === undefined ? fallback : raw;
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`reader-steering plugin ${label} must be a number from ${minimum} to ${maximum}`);
  }
  return value;
}

function flag(raw: unknown, label: string): boolean {
  if (raw === undefined) return false;
  if (typeof raw !== "boolean") throw new Error(`reader-steering plugin ${label} must be a boolean`);
  return raw;
}

function names(raw: unknown, label: string, pattern: RegExp): string[] {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || !raw.every((entry) => typeof entry === "string" && pattern.test(entry))) {
    throw new Error(`reader-steering plugin ${label} must be a list of lowercase names matching ${pattern}`);
  }
  return [...new Set(raw as string[])];
}

export function resolveReaderSteeringConfig(request: PluginRequest): ReaderSteeringConfig {
  const raw = typeof request === "string" ? { name: request } : request;
  const unknown = Object.keys(raw).filter((key) => !KNOWN_KEYS.has(key));
  if (unknown.length > 0) throw new Error(`Unknown reader-steering plugin settings: ${unknown.join(", ")}`);
  const computeRoleArn = raw.computeRoleArn;
  if (typeof computeRoleArn !== "string" || !COMPUTE_ROLE_ARN.test(computeRoleArn)) {
    throw new Error("reader-steering plugin computeRoleArn must be the IAM role ARN of the CMS app's compute role (the CmsComputeRoleArn output)");
  }
  const dimensions = names(raw.dimensions, "dimensions", READER_DIMENSION_NAME);
  const reserved = dimensions.filter((dimension) => RESERVED_DIMENSIONS.includes(dimension));
  if (reserved.length > 0) throw new Error(`reader-steering plugin dimensions cannot use the reserved names: ${reserved.join(", ")}`);
  const limits = object(raw.limits, "limits", ["actionsPerHour", "newAccountHours", "newAccountDivisor"]);
  const karma = object(raw.karma, "karma", ["upvoteWeight", "usedItWeight"]);
  const ranking = object(raw.ranking, "ranking", ["halfLifeHours", "risingWindowHours", "readerMinimum", "editorWeight"]);
  const snapshot = object(raw.snapshot, "snapshot", ["schedule", "intervalHours", "hypeMinimum"]);
  const retirementPoll = flag(raw.retirementPoll, "retirementPoll");
  if (retirementPoll && !flag(snapshot.schedule, "snapshot.schedule")) {
    throw new Error("reader-steering plugin retirementPoll runs inside the scheduled snapshot, so it needs snapshot.schedule: true");
  }
  return {
    computeRoleArn,
    dimensions,
    limits: {
      actionsPerHour: integer(limits.actionsPerHour, "limits.actionsPerHour", 120, 1, 10000),
      newAccountHours: integer(limits.newAccountHours, "limits.newAccountHours", 24, 0, 24 * 90),
      newAccountDivisor: integer(limits.newAccountDivisor, "limits.newAccountDivisor", 3, 1, 100),
    },
    reservedHandles: names(raw.reservedHandles, "reservedHandles", READER_HANDLE_NAME),
    karma: {
      upvoteWeight: number(karma.upvoteWeight, "karma.upvoteWeight", 1, 0, 1000),
      usedItWeight: number(karma.usedItWeight, "karma.usedItWeight", 2, 0, 1000),
    },
    ranking: {
      halfLifeHours: number(ranking.halfLifeHours, "ranking.halfLifeHours", 48, 1, 24 * 365),
      risingWindowHours: number(ranking.risingWindowHours, "ranking.risingWindowHours", 6, 1, 24 * 30),
      readerMinimum: integer(ranking.readerMinimum, "ranking.readerMinimum", 5, 1, 10000),
      editorWeight: number(ranking.editorWeight, "ranking.editorWeight", 0.5, 0, 1),
    },
    snapshot: {
      schedule: flag(snapshot.schedule, "snapshot.schedule"),
      intervalHours: integer(snapshot.intervalHours, "snapshot.intervalHours", 6, 1, 24),
      hypeMinimum: integer(snapshot.hypeMinimum, "snapshot.hypeMinimum", 5, 1, 10000),
    },
    retirementPoll,
  };
}
