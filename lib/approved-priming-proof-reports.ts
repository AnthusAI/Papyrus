/**
 * Priming proof reports a publication owner approved for visitors, keyed by site brand id.
 * A report reaches this map only through a reviewed commit of its
 * `publications/priming-proofs/<brand id>.json` file; see docs/cyclotron-priming.md.
 */
export const APPROVED_PRIMING_PROOF_REPORTS: Record<string, unknown> = {};
