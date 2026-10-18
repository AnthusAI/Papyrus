import approvedReport0 from "../publications/priming-proofs/papyrus.json";

/**
 * Priming proof reports a publication owner approved for visitors, keyed by site brand id.
 * A report reaches this map only through a reviewed commit made by scripts/approve-priming-proof-report.ts.
 */
export const APPROVED_PRIMING_PROOF_REPORTS: Record<string, unknown> = {
  "papyrus": approvedReport0,
};
