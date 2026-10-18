"use client";

import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { resolveArticlesBackend } from "../lib/newsroom-articles";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { DEFAULT_WIKI_INDEX_MARKUS, WIKI_INDEX_SLUG, WIKI_PAGE_ITEM_TYPE } from "../lib/wiki";
import { configureAmplifyClient } from "./amplify-client-provider";

export type WikiIndexPage = {
  /** The id of the stored content item, or null while the wiki still shows the built-in starter content. */
  itemId: string | null;
  bodyMarkus: string;
  bodyIr: unknown;
};

type GraphqlResponse = { data?: { itemBySlug?: { items?: Record<string, unknown>[] | null } | null } | null; errors?: { message?: string }[] | null };

async function storedIndexRow(preview: boolean): Promise<Record<string, unknown> | null> {
  if (preview || isLocalPreviewEnabled()) return null;
  configureAmplifyClient();
  const client = generateClient<Schema>() as unknown as { graphql: (options: Record<string, unknown>) => Promise<GraphqlResponse> };
  const response = await client.graphql({
    query: "query ($slug: String!) { itemBySlug(slug: $slug) { items { id versionNumber versionState bodyMarkus bodyIr } } }",
    variables: { slug: WIKI_INDEX_SLUG },
    authMode: "userPool",
  });
  if (response.errors?.length) throw new Error(response.errors.map(error => error.message ?? "GraphQL error").join("; "));
  const rows = (response.data?.itemBySlug?.items ?? []).filter(Boolean) as Record<string, unknown>[];
  const ranked = rows.sort((left, right) => Number(right.versionNumber ?? 0) - Number(left.versionNumber ?? 0));
  return ranked.find(row => row.versionState === "current") ?? ranked[0] ?? null;
}

async function derive(bodyMarkus: string, preview: boolean): Promise<unknown> {
  const result = await resolveArticlesBackend(preview).actions.deriveMarkus({ frontMatterYaml: null, bodyMarkus, includeIr: true });
  return result.bodyIr ?? null;
}

/** Loads the wiki's front page content item, falling back to the starter content until one is saved. */
export async function loadWikiIndexPage(preview: boolean): Promise<WikiIndexPage> {
  const row = await storedIndexRow(preview);
  const bodyMarkus = typeof row?.bodyMarkus === "string" && row.bodyMarkus.trim() ? row.bodyMarkus : DEFAULT_WIKI_INDEX_MARKUS;
  const storedIr = row?.bodyIr;
  return { itemId: row ? String(row.id) : null, bodyMarkus, bodyIr: storedIr ?? await derive(bodyMarkus, preview) };
}

/** Saves the starter index as the wiki-index content item so editors can change it like any other page. */
export async function createWikiIndexPage(preview: boolean): Promise<WikiIndexPage> {
  const saved = await resolveArticlesBackend(preview).actions.saveItemDraft({ id: null, type: WIKI_PAGE_ITEM_TYPE, slug: WIKI_INDEX_SLUG, section: null, frontMatterYaml: `title: Concept wiki\n`, bodyMarkus: DEFAULT_WIKI_INDEX_MARKUS, aliases: [], expectedContentHash: null });
  return { itemId: saved.item.id, bodyMarkus: DEFAULT_WIKI_INDEX_MARKUS, bodyIr: await derive(DEFAULT_WIKI_INDEX_MARKUS, preview) };
}
