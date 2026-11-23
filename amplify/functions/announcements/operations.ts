/** The operations the function serves. The console client and the schema both read this list, so they cannot drift apart. */
export const ANNOUNCEMENT_QUERY_OPERATIONS = ["announcementsSettings", "announcementsXStatus", "announcementsXUsage", "announcementsXSpend"] as const;
export const ANNOUNCEMENT_MUTATION_OPERATIONS = [
  "announcementsSaveSettings", "announcementsPause", "announcementsXSaveApp", "announcementsXBegin", "announcementsXComplete", "announcementsXDisconnect",
] as const;

/** A billed read, explicitly triggered by a person. It reserves a spend allowance but never writes to X. */
export const OPPORTUNITY_MUTATION_OPERATIONS = ["opportunitiesXSearch"] as const;
