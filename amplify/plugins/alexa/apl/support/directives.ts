import type { PublicStory, PublicStorySummary } from "../../contracts";
import { FEED_DATASOURCE, feedDocument } from "../feed";
import { STORY_DATASOURCE, storyDocument } from "../story";
import type { AplTheme } from "./theme";

export type RenderDocumentDirective = {
  type: "Alexa.Presentation.APL.RenderDocument";
  token: string;
  document: Record<string, unknown>;
  datasources: Record<string, unknown>;
};

/** A story as the screen shows it. `imageUrl` is optional: the content source adds it once stories carry a lead image. */
export type AplStorySummary = PublicStorySummary & { imageUrl?: string };

function render(document: { id: string; document: Record<string, unknown> }, datasources: Record<string, unknown>): RenderDocumentDirective {
  return { type: "Alexa.Presentation.APL.RenderDocument", token: document.id, document: document.document, datasources };
}

function dateline(publishedAt: string): string | undefined {
  const date = new Date(publishedAt);
  if (Number.isNaN(date.getTime())) return undefined;
  return date.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}

/**
 * The RenderDocument directive for the feed. Each story keeps its position as `index`, which a touched card sends back in the
 * UserEvent. `publication` is the name shown in the header (the skill name).
 */
export function feedDirective(stories: readonly AplStorySummary[], theme: AplTheme, publication = ""): RenderDocumentDirective {
  return render(feedDocument, {
    [FEED_DATASOURCE]: {
      publication,
      theme,
      stories: stories.map((story, index) => ({
        index,
        title: story.title,
        ...(story.deck === undefined ? {} : { deck: story.deck }),
        ...(story.byline === undefined ? {} : { byline: story.byline }),
        ...(story.imageUrl === undefined ? {} : { imageUrl: story.imageUrl }),
      })),
    },
  });
}

/** The RenderDocument directive for one story. `bodyParagraphs` is the plain text of the body, one entry per paragraph. */
export function storyDirective(story: PublicStory & { imageUrl?: string }, bodyParagraphs: readonly string[], theme: AplTheme): RenderDocumentDirective {
  const meta = [story.byline, dateline(story.publishedAt)].filter((part): part is string => part !== undefined && part.length > 0).join(" · ");
  return render(storyDocument, {
    [STORY_DATASOURCE]: {
      title: story.title,
      meta,
      ...(story.imageUrl === undefined ? {} : { imageUrl: story.imageUrl }),
      paragraphs: [...bodyParagraphs],
      theme,
    },
  });
}
