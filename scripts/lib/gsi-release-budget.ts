// The release budget of the GSI ledger: how many index creations one release may hold so its backend deploy fits Amplify's build timeout.
// DynamoDB backfills a new global secondary index, and CloudFormation updates the model stacks in waves, so deploy time grows with the number of
// tables that gain an index. The seconds per creation are MEASURED (scripts/data/gsi-deploy-measurements.json, appended after each release that
// created indexes), never guessed. Rules: features_backend/gsi-ledger.feature.

export interface Measurement {
  date: string;
  label: string;
  /** Indexes the release created. */
  indexCreations: number;
  /** Seconds the data stack update took, from CloudFormation's stack events. */
  deploySeconds: number;
  note?: string;
}

export interface MeasurementFile {
  reservedMinutes: number;
  safetyMargin: number;
  measurements: Measurement[];
}

export interface Budget {
  /** Index creations that fit one release. */
  limit: number;
  secondsPerCreation: number;
  buildTimeoutMinutes: number;
  reservedMinutes: number;
  safetyMargin: number;
  /** The measurement the seconds per creation come from. */
  measuredOn: string;
}

export function parseMeasurementFile(value: unknown): MeasurementFile {
  const file = value as MeasurementFile;
  const bad = (problem: string): never => { throw new Error(`GSI release budget: ${problem}`); };
  if (!file || typeof file !== "object") return bad("the measurement file is not an object.");
  if (!Number.isFinite(file.reservedMinutes) || file.reservedMinutes < 0) bad("reservedMinutes must be a number of minutes.");
  if (!Number.isFinite(file.safetyMargin) || file.safetyMargin < 0 || file.safetyMargin >= 1) bad("safetyMargin must be at least 0 and below 1.");
  if (!Array.isArray(file.measurements) || file.measurements.length === 0) bad("the file holds no measurement; the budget is derived from measurements, so measure a release first.");
  for (const entry of file.measurements) {
    if (!(entry.indexCreations > 0) || !(entry.deploySeconds > 0) || !/^\d{4}-\d{2}-\d{2}$/.test(entry.date)) {
      bad(`a measurement needs a date, a positive indexCreations and a positive deploySeconds: ${JSON.stringify(entry)}`);
    }
  }
  return file;
}

export const secondsPerCreation = (entry: Measurement): number => entry.deploySeconds / entry.indexCreations;

/**
 * The index creations that fit one release: (build timeout less the reserved minutes, less the safety margin) divided by the slowest measured
 * seconds per creation. The slowest measurement is the one that holds, so a later fast release never loosens the budget.
 */
export function releaseBudget(file: MeasurementFile, buildTimeoutMinutes: number): Budget {
  const slowest = file.measurements.reduce((worst, entry) => (secondsPerCreation(entry) > secondsPerCreation(worst) ? entry : worst));
  const seconds = secondsPerCreation(slowest);
  const available = Math.max(buildTimeoutMinutes - file.reservedMinutes, 0) * 60 * (1 - file.safetyMargin);
  return {
    limit: Math.floor(available / seconds),
    secondsPerCreation: seconds,
    buildTimeoutMinutes,
    reservedMinutes: file.reservedMinutes,
    safetyMargin: file.safetyMargin,
    measuredOn: slowest.date,
  };
}

/** Splits the pending indexes into releases of at most `limit` creations, keeping the one-per-table order of the ledger's own release groups. */
export function chunkReleases(groups: [string, string][][], limit: number): [string, string][][] {
  const releases: [string, string][][] = [];
  for (const group of groups) {
    for (let start = 0; start < group.length; start += Math.max(limit, 1)) releases.push(group.slice(start, start + Math.max(limit, 1)));
  }
  return releases;
}

export const estimatedMinutes = (creations: number, budget: Budget): number => Math.ceil((creations * budget.secondsPerCreation) / 60);

export const describeBudget = (budget: Budget): string =>
  `${budget.limit} index creations fit one release: build timeout ${budget.buildTimeoutMinutes} min, less ${budget.reservedMinutes} min reserved, ` +
  `less a ${Math.round(budget.safetyMargin * 100)}% margin, at ${Math.round(budget.secondsPerCreation)} s per creation (measured ${budget.measuredOn}).`;

export interface StackEvent {
  LogicalResourceId: string;
  ResourceType: string;
  ResourceStatus: string;
  Timestamp: string;
}

/**
 * Seconds the data stack's last update took, from the root stack's events: the last time the nested stack whose logical id starts with `data`
 * went UPDATE_IN_PROGRESS to the next UPDATE_COMPLETE. Throws while that update is still running, so a release is measured once it finished.
 */
export function dataStackSeconds(events: StackEvent[]): number {
  const data = events
    .filter((event) => event.ResourceType === "AWS::CloudFormation::Stack" && /^data[0-9A-F]{8}$/.test(event.LogicalResourceId))
    .sort((a, b) => Date.parse(a.Timestamp) - Date.parse(b.Timestamp));
  const started = data.filter((event) => event.ResourceStatus === "UPDATE_IN_PROGRESS").at(-1);
  if (!started) throw new Error("GSI release budget: the root stack events hold no data stack update.");
  const finished = data.find((event) => event.ResourceStatus === "UPDATE_COMPLETE" && Date.parse(event.Timestamp) > Date.parse(started.Timestamp));
  if (!finished) throw new Error("GSI release budget: the data stack update has not finished; measure after it completes.");
  return Math.round((Date.parse(finished.Timestamp) - Date.parse(started.Timestamp)) / 1000);
}
