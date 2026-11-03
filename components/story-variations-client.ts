"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { previewVariations, updatePreviewVariation } from "../lib/local-preview-variations";
import { readVariation, sortVariations, VARIATION_FIELDS, type StoryVariationView } from "../lib/story-variations";
import { configureAmplifyClient } from "./amplify-client-provider";

type GraphqlResponse = { data?: Record<string, { items?: Record<string, unknown>[] | null; nextToken?: string | null } | null> | null; errors?: { message?: string }[] | null };
type GraphqlClient = { graphql: (options: Record<string, unknown>) => Promise<GraphqlResponse> };

const USER_POOL = "userPool";

/** Where the variations of a Story are read and decided. The page uses the API; the tests and the local preview give their own. */
export type VariationSource = {
  load: (storyLineageId: string) => Promise<StoryVariationView[]>;
  decide: (variation: StoryVariationView, decision: "accepted" | "rejected", by: { label: string }, reason: string, siblings: readonly StoryVariationView[]) => Promise<void>;
};

async function graphql(client: GraphqlClient, query: string, variables: Record<string, unknown>): Promise<GraphqlResponse> {
  const response = await client.graphql({ query, variables, authMode: USER_POOL });
  if (response.errors?.length) throw new Error(response.errors.map((error) => error.message ?? "GraphQL error").join("; "));
  return response;
}

export const apiVariationSource: VariationSource = {
  async load(storyLineageId) {
    configureAmplifyClient();
    const client = generateClient<Schema>() as unknown as GraphqlClient;
    const rows: Record<string, unknown>[] = [];
    let nextToken: string | null = null;
    do {
      const response: GraphqlResponse = await graphql(client, `query ($storyLineageId: ID!, $nextToken: String) { listStoryVariationsByStoryAndNumber(storyLineageId: $storyLineageId, limit: 100, nextToken: $nextToken) { items { ${VARIATION_FIELDS} } nextToken } }`, { storyLineageId, nextToken });
      const connection = response.data?.listStoryVariationsByStoryAndNumber;
      rows.push(...((connection?.items ?? []).filter(Boolean) as Record<string, unknown>[]));
      nextToken = connection?.nextToken ?? null;
    } while (nextToken);
    return sortVariations(rows.map(readVariation));
  },
  async decide(variation, decision, by, reason, siblings) {
    configureAmplifyClient();
    const client = generateClient<Schema>() as unknown as GraphqlClient;
    const now = new Date().toISOString();
    const update = (input: Record<string, unknown>) => graphql(client, "mutation ($input: UpdateStoryVariationInput!) { updateStoryVariation(input: $input) { id } }", { input });
    // A Story has one accepted variation at a time: accepting this one puts the earlier one back on offer (docs/story-variations.md).
    if (decision === "accepted") {
      for (const other of siblings) if (other.id !== variation.id && other.status === "accepted") await update({ id: other.id, status: "offered", updatedAt: now });
    }
    await update({ id: variation.id, status: decision, decidedByLabel: by.label, decidedAt: now, decisionReason: reason.trim() || null, updatedAt: now });
  },
};

export const previewVariationSource: VariationSource = {
  async load(storyLineageId) { return sortVariations(previewVariations(storyLineageId)); },
  async decide(variation, decision, by, reason) {
    updatePreviewVariation({ ...variation, status: decision, decidedByLabel: by.label, decidedAt: new Date().toISOString(), decisionReason: reason.trim() || null }, decision === "accepted");
  },
};

/** The demo workspace (and the tests that render it) has no variations: it reads and shows none. Only the local preview has sample ones. */
export const emptyVariationSource: VariationSource = { async load() { return []; }, async decide() { /* nothing to decide */ } };

export function resolveVariationSource(demo: boolean): VariationSource {
  if (isLocalPreviewEnabled()) return previewVariationSource;
  return demo ? emptyVariationSource : apiVariationSource;
}
