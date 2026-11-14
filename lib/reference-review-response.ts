// What the newsroom checks in a saved vote's response. A vote is recorded on the Reference itself and writes no Message
// or relation (Messages come only from people), so the response carries only the outcome.
export type ReferenceReviewResult = {
  ok?: boolean | null;
  action?: string | null;
  referenceId?: string | null;
  status?: string | null;
  reasonCode?: string | null;
};

export function assertReferenceReviewSaved(data: ReferenceReviewResult | null | undefined, referenceId: string): ReferenceReviewResult {
  if (!data?.ok) {
    throw new Error(`Reference curation review was not saved for ${referenceId}.`);
  }
  if (data.referenceId && data.referenceId !== referenceId) {
    throw new Error(`Reference review response did not match ${referenceId}.`);
  }
  return data;
}
