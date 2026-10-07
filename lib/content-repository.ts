import type { ContentRepository } from "./content-types";
import { graphqlContentRepository } from "./graphql-content-repository";
import { getLayoutScenario } from "./layout-scenarios";
import { assertContentSourceMatchesEnv } from "./site-env";

assertContentSourceMatchesEnv();

export const contentRepository: ContentRepository = {
  loadEditionContent({ scenarioId, editionDate, editionSlug } = {}) {
    if (scenarioId) return getLayoutScenario(scenarioId);
    return graphqlContentRepository.loadEditionContent({ editionDate, editionSlug });
  },
  getLatestPublishedEdition() {
    return graphqlContentRepository.getLatestPublishedEdition();
  },
  getFirstPublishedEdition() {
    return graphqlContentRepository.getFirstPublishedEdition();
  },
  listPublishedEditions(options) {
    return graphqlContentRepository.listPublishedEditions(options);
  },
  getArticle(slug: string) {
    return graphqlContentRepository.getArticle(slug);
  },
  getEditionArticle(options) {
    return graphqlContentRepository.getEditionArticle(options);
  },
  getEditionItem(options) {
    return graphqlContentRepository.getEditionItem(options);
  },
  listArticleSlugs() {
    return graphqlContentRepository.listArticleSlugs();
  },
  loadVideoScript(targetSlug: string) {
    return graphqlContentRepository.loadVideoScript(targetSlug);
  },
};

export function getScenarioIdParam(scenario: string | string[] | null | undefined): string | null {
  if (Array.isArray(scenario)) return scenario[0] ?? null;
  return scenario ?? null;
}

export function isGraphQLContentSource(): boolean {
  return true;
}
