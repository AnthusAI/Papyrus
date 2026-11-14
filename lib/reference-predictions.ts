/**
 * Predictions for the References the feed shows, one indexed read per Reference (its relations by subject), run a few at a time.
 * There is no budget on how many relations a newsroom holds: the cost grows with what is on screen, never with the size of the newsroom.
 * The only bound is how many reads are in flight at once, which protects the browser and the API, not the data.
 */
export type PredictionStatus = { state: "loading" } | { state: "ready" } | { state: "error"; error: string };

export type PredictionStatuses = ReadonlyMap<string, PredictionStatus>;

/** Reads in flight at once. A concurrency bound, not a cap on how many References are read. */
export const PREDICTION_READ_CONCURRENCY = 6;

function describe(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "The prediction could not be read.";
}

/**
 * Read every id with `load`, at most `concurrency` at a time. Each id settles on its own: one failure is reported for that id only
 * and never stops the others. Results are reported as they arrive, so cards fill in one by one.
 */
export async function loadPredictionsForReferences<Relation>(
  ids: readonly string[],
  load: (lineageId: string) => Promise<Relation[]>,
  report: {
    ready: (lineageId: string, relations: Relation[]) => void;
    failed: (lineageId: string, error: string) => void;
  },
  concurrency = PREDICTION_READ_CONCURRENCY,
): Promise<void> {
  let next = 0;
  const worker = async () => {
    while (next < ids.length) {
      const lineageId = ids[next];
      next += 1;
      try {
        report.ready(lineageId, await load(lineageId));
      } catch (error) {
        report.failed(lineageId, describe(error));
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(Math.max(1, concurrency), ids.length) }, worker));
}

/** True once every id has either its prediction or a per-card failure. Ids nobody asked about yet are not settled. */
export function predictionsSettled(ids: Iterable<string>, statuses: PredictionStatuses): boolean {
  for (const id of ids) {
    const status = statuses.get(id);
    if (!status || status.state === "loading") return false;
  }
  return true;
}
