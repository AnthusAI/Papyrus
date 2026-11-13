/** The operations the function serves. The console client and the schema both read this list, so they cannot drift apart. */
export const ANNOUNCEMENT_QUERY_OPERATIONS = ["announcementsSettings", "announcementsXStatus", "announcementsXUsage"] as const;
export const ANNOUNCEMENT_MUTATION_OPERATIONS = [
  "announcementsSaveSettings", "announcementsPause", "announcementsXSaveApp", "announcementsXBegin", "announcementsXComplete", "announcementsXDisconnect",
] as const;
