"use client";

/**
 * The newsroom's front end for the announcements door: `announcementsRead`, which only reads (the Story drawer's lines and the Announcements list). The door takes who is asking
 * from the signed-in session; the browser only says which operation and its input. What changes an announcement stays on the command line and in the agents' tools.
 */
import { generateClient } from "aws-amplify/data";
import { configureAmplifyClient } from "../components/amplify-client-provider";
import { callImageOperation } from "./images/operations.generated";
import type { AnnouncementsDoor } from "./announcement-lines";

const GRAPHQL_READ = `query AnnouncementsRead($op: String!, $input: AWSJSON) { announcementsRead(op: $op, input: $input) }`;

export const announcementsDoor: AnnouncementsDoor = ((op, input) => callImageOperation(op, input, async ({ op: name, input: body }) => {
  configureAmplifyClient();
  const client = generateClient({ authMode: "userPool" });
  const response = (await client.graphql({ query: GRAPHQL_READ, variables: { op: name, input: JSON.stringify(body ?? {}) } })) as { data?: Record<string, unknown>; errors?: { message?: string }[] };
  if (response.errors?.length) throw new Error("The announcements service did not answer. It may not be on this site yet.");
  const raw = response.data?.announcementsRead;
  return typeof raw === "string" ? JSON.parse(raw) : raw;
})) as AnnouncementsDoor;
