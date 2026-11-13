// The GSI ledger: compares the secondary indexes of every data model in two copies of the schema sources: amplify/data/schema.ts and every
// plugin's and function's schema.ts (SCHEMA_SOURCE), which together are the deployed tables.
// DynamoDB lets one update create or delete one global secondary index on a table.
// Rules (features_backend/gsi-ledger.feature):
//   - a table that gains more than one index since the baseline fails;
//   - an index that keeps its name but changes its keys fails;
//   - a table with more than TABLE_LIMIT indexes fails;
//   - every table whose indexes changed reports how many index slots it has left.

/** The DynamoDB limit of global secondary indexes per table (AWS docs, "Service, account, and table quotas in Amazon DynamoDB": Global secondary indexes per table). */
export const TABLE_LIMIT = 20;

export interface IndexEntry {
  /** The index name when set, otherwise its query field: what DynamoDB sees as the index. */
  id: string;
  keys: string;
}
export type Ledger = Map<string, IndexEntry[]>;

export interface Report {
  failures: string[];
  warnings: string[];
  slots: string[];
  releaseOrder: string[];
}

/** The files that declare data models: the core schema and each plugin's and function's own schema. */
export const SCHEMA_SOURCE = /^amplify\/(?:data|plugins\/[^/]+|functions\/[^/]+)\/schema\.ts$/;

// A model starts at `Name: modelWithoutSubscriptions(`, `Name: realtimeModel(` or `Name: a.model(` (the plugin files break the line before `.model`).
const MODEL_START = /^( +)(\w+): (?:modelWithoutSubscriptions|realtimeModel|a\s*\.model)\(/gm;
const INDEX_CALL = /index\("(\w+)"\)((?:\.\w+\((?:[^()]|\([^()]*\))*\))*)/g;

export function parseLedger(source: string): Ledger {
  const starts = [...source.matchAll(MODEL_START)];
  const ledger: Ledger = new Map();
  starts.forEach((start, position) => {
    const end = position + 1 < starts.length ? starts[position + 1].index! : source.length;
    // A model ends at the next entry of the schema at its own indentation, which may be a custom type, query or mutation.
    const block = source.slice(start.index!, end).split(new RegExp(`^${start[1]}\\w+: a\\s*\\.(?!model)`, "m"))[0];
    const entries: IndexEntry[] = [];
    for (const call of block.matchAll(INDEX_CALL)) {
      const [, partitionKey, chain] = call;
      const sortKeys = /\.sortKeys\(\[([^\]]*)\]\)/.exec(chain)?.[1].replace(/["'\s]/g, "") ?? "";
      const name = /\.name\("(\w+)"\)/.exec(chain)?.[1];
      const queryField = /\.queryField\("(\w+)"\)/.exec(chain)?.[1];
      entries.push({ id: name ?? queryField ?? `${partitionKey}:${sortKeys}`, keys: `${partitionKey}|${sortKeys}` });
    }
    ledger.set(start[2], entries);
  });
  return ledger;
}

/** One ledger of several schema files; a model declared in two files fails, since each model is one table. */
export function parseLedgers(sources: { path: string; source: string }[]): Ledger {
  const ledger: Ledger = new Map();
  const declaredIn = new Map<string, string>();
  for (const { path, source } of sources) {
    for (const [table, entries] of parseLedger(source)) {
      if (declaredIn.has(table)) throw new Error(`GSI ledger: ${table} is declared in both ${declaredIn.get(table)} and ${path}.`);
      declaredIn.set(table, path);
      ledger.set(table, entries);
    }
  }
  return ledger;
}

export function compareLedgers(baseline: Ledger, current: Ledger): Report {
  const report: Report = { failures: [], warnings: [], slots: [], releaseOrder: [] };
  const pending: [string, string][][] = [];
  for (const [table, entries] of current) {
    if (entries.length > TABLE_LIMIT) {
      report.failures.push(`${table} has ${entries.length} indexes; DynamoDB allows ${TABLE_LIMIT} per table.`);
    }
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
    const kept = new Set(entries.map((entry) => entry.id));
    const dropped = [...before.keys()].filter((id) => !kept.has(id));
    if (added.length || dropped.length) {
      report.slots.push(`${table} has ${entries.length} of ${TABLE_LIMIT} indexes: ${Math.max(TABLE_LIMIT - entries.length, 0)} left.`);
    }
    added.forEach((entry, position) => {
      (pending[position] ??= []).push([table, entry.id]);
    });
    if (baseline.has(table)) for (const gone of dropped) report.warnings.push(`${table} drops index ${gone}.`);
  }
  pending.forEach((group, position) => {
    report.releaseOrder.push(`release ${position + 1}: ${group.map(([table, id]) => `${table}.${id}`).join(", ")}`);
  });
  return report;
}
