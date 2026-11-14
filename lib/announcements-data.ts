import type { AnnouncementRow } from "./announcements-model";

/** The announcement backend (PPY-9f4d66) is not in this repository's data API yet. */
export class AnnouncementsBackendNotDeployed extends Error {
  constructor() {
    super("The announcement list needs the announcement backend (PPY-9f4d66), which is not deployed on this site yet.");
  }
}

export type AnnouncementsSource = { list: () => Promise<AnnouncementRow[]> };

/**
 * STUB, named on purpose: the data layer for the dry-run preview and the audit list. When PPY-9f4d66 lands, replace this
 * with the operation behind `papyrus announcements list` (rows carry the Story, state, exact text, link, post id, cost
 * and error, per the plan's audit trail). Until then it fails clearly and the page says so; it never invents rows.
 */
export const announcementsSource: AnnouncementsSource = {
  async list() {
    throw new AnnouncementsBackendNotDeployed();
  },
};
