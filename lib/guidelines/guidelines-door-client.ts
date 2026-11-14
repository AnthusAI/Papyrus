"use client";

/**
 * The newsroom's front end for the guidelines door: `guidelinesRead` for operations that only read, `guidelinesWrite` for the ones that save. The door takes who is
 * asking from the signed-in session; the browser only says which operation and its input (docs/plans/guidelines-as-data.md section 5). The Story picker reads one
 * newest-first page of published Stories per Story type from the published-by-type-and-date index.
 */
import { generateClient } from "aws-amplify/data";
import { configureAmplifyClient } from "../../components/amplify-client-provider";
import { callImageOperation } from "../images/operations.generated";
import type { GuidelinesDoor, ListPublishedStories, PublishedStory } from "./writing-guidelines-admin";

const GRAPHQL_READ = `query GuidelinesRead($op: String!, $input: AWSJSON) { guidelinesRead(op: $op, input: $input) }`;
const GRAPHQL_WRITE = `mutation GuidelinesWrite($op: String!, $input: AWSJSON, $requestId: ID!) { guidelinesWrite(op: $op, input: $input, requestId: $requestId) }`;

export const guidelinesDoor: GuidelinesDoor = (op, input) => callImageOperation(op, input, async ({ op: name, input: body, effect }) => {
  configureAmplifyClient();
  const client = generateClient({ authMode: "userPool" });
  const payload = JSON.stringify(body ?? {});
  const response = (await client.graphql(effect === "read"
    ? { query: GRAPHQL_READ, variables: { op: name, input: payload } }
    : { query: GRAPHQL_WRITE, variables: { op: name, input: payload, requestId: crypto.randomUUID() } })) as { data?: Record<string, unknown>; errors?: { message?: string }[] };
  if (response.errors?.length) throw new Error(response.errors[0]?.message ?? "The guidelines service could not be reached.");
  const raw = response.data?.[effect === "read" ? "guidelinesRead" : "guidelinesWrite"];
  return typeof raw === "string" ? JSON.parse(raw) : raw;
});

const PICKER_PAGE_SIZE = 50;

/** The newest published Stories, one index page per Story type (the published-by-type-and-date index). Nothing is scanned. */
export const listPublishedStories: ListPublishedStories = async () => {
  configureAmplifyClient();
  const { siteStoryTypes } = await import("../site-story-types");
  const client = generateClient({ authMode: "userPool" }) as any;
  const pages = await Promise.all(siteStoryTypes().types.map((type: string) =>
    client.models.PublishedItem.listPublishedItemsByTypeStatusAndPublishedAt({ typeStatus: `${type}#published` }, { limit: PICKER_PAGE_SIZE, sortDirection: "DESC", authMode: "userPool" })));
  const stories = new Map<string, PublishedStory>();
  for (const page of pages) for (const row of page.data ?? []) {
    const lineageId = row.itemLineageId ?? row.sourceItemId;
    if (lineageId && !stories.has(lineageId)) stories.set(lineageId, { lineageId, title: row.title || row.slug || lineageId });
  }
  return [...stories.values()];
};
