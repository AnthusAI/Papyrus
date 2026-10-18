const missingMediaWarningsAlreadyLogged = new Set<string>();

/** A story without its lead image must still publish; the layout renders without the slot. */
export function warnAboutMissingMedia(message: string): void {
  if (missingMediaWarningsAlreadyLogged.has(message)) return;
  missingMediaWarningsAlreadyLogged.add(message);
  console.warn(`[layout-plan] ${message}`);
}
