// The GSI ledger: compares the secondary indexes of every data model in two copies of amplify/data/schema.ts.
// DynamoDB lets one update create or delete one global secondary index on a table, and a table holds at most 20.
// Rules (features_backend/gsi-ledger.feature):
//   - a table that gains more than one index since the baseline fails;
//   - an index that keeps its name but changes its keys fails;
//   - a table with more than FAIL_ABOVE indexes fails; one with WARN_AT or more warns.
export const TABLE_LIMIT = 20;
export const FAIL_ABOVE = 18;
export const WARN_AT = 16;

export interface IndexEntry {
  /** The index name when set, otherwise its query field: what DynamoDB sees as the index. */
  id: string;
  keys: string;
}
export type Ledger = Map<string, IndexEntry[]>;

export interface Report {
  failures: string[];
  warnings: string[];
  releaseOrder: string[];
}

const MODEL_START = /^  (\w+): (?:modelWithoutSubscriptions|realtimeModel|a\.model)\(/gm;
const INDEX_CALL = /index\("(\w+)"\)((?:\.\w+\((?:[^()]|\([^()]*\))*\))*)/g;

export function parseLedger(source: string): Ledger {
  const starts = [...source.matchAll(MODEL_START)];
  const ledger: Ledger = new Map();
  starts.forEach((start, position) => {
    const end = position + 1 < starts.length ? starts[position + 1].index! : source.length;
    // A model ends at the next top-level entry of the schema, which may be a custom type or query.
    const block = source.slice(start.index!, end).split(/^  (?:\w+): a\.(?!model)/m)[0];
    const entries: IndexEntry[] = [];
    for (const call of block.matchAll(INDEX_CALL)) {
      const [, partitionKey, chain] = call;
      const sortKeys = /\.sortKeys\(\[([^\]]*)\]\)/.exec(chain)?.[1].replace(/["'\s]/g, "") ?? "";
      const name = /\.name\("(\w+)"\)/.exec(chain)?.[1];
      const queryField = /\.queryField\("(\w+)"\)/.exec(chain)?.[1];
      entries.push({ id: name ?? queryField ?? `${partitionKey}:${sortKeys}`, keys: `${partitionKey}|${sortKeys}` });
    }
    ledger.set(start[1], entries);
  });
  return ledger;
}

export function compareLedgers(baseline: Ledger | undefined, current: Ledger): Report {
  const report: Report = { failures: [], warnings: [], releaseOrder: [] };
  const pending: [string, string][][] = [];
  for (const [table, entries] of current) {
    if (entries.length > FAIL_ABOVE) {
      report.failures.push(`${table} has ${entries.length} indexes; more than ${FAIL_ABOVE} is refused (DynamoDB allows ${TABLE_LIMIT}).`);
    } else if (entries.length >= WARN_AT) {
      report.warnings.push(`${table} has ${entries.length} of the ${TABLE_LIMIT} indexes DynamoDB allows; new indexes need a different shape.`);
    }
    if (!baseline) continue;
    const before = new Map((baseline.get(table) ?? []).map((entry) => [entry.id, entry]));
    const added = entries.filter((entry) => !before.has(entry.id));
    for (const entry of entries) {
      const old = before.get(entry.id);
      if (old && old.keys !== entry.keys) {
        report.failures.push(`${table} index ${entry.id} changed its keys in place (${old.keys} to ${entry.keys}); add a new index and remove this one in a later release.`);
      }
    }
    if (added.length > 1) {
      report.failures.push(`${table} gains ${added.length} indexes in one release: ${added.map((entry) => entry.id).join(", ")}. Ship one per release.`);
    }
    added.forEach((entry, position) => {
      (pending[position] ??= []).push([table, entry.id]);
    });
    const kept = new Set(entries.map((entry) => entry.id));
    for (const gone of before.keys()) {
      if (!kept.has(gone) && baseline.has(table)) report.warnings.push(`${table} drops index ${gone}.`);
    }
  }
  pending.forEach((group, position) => {
    report.releaseOrder.push(`release ${position + 1}: ${group.map(([table, id]) => `${table}.${id}`).join(", ")}`);
  });
  return report;
}
