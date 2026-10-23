/** Hold the lock before invoking a save, including before React can rerender. */
export function runReferenceReviewRequest(
  pending: Map<string, Promise<void>>,
  lineageId: string,
  save: () => Promise<void>,
): Promise<void> {
  const existing = pending.get(lineageId);
  if (existing) return existing;
  const request = Promise.resolve().then(save).finally(() => {
    if (pending.get(lineageId) === request) pending.delete(lineageId);
  });
  pending.set(lineageId, request);
  return request;
}
