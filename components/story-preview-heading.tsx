import { storyHeadings } from "../lib/front-matter-fields";

/** Opens the Preview pane the way a reader meets the Story: the headline first, then the deck, then the blurb. The deck never stands in the headline's place. */
export function StoryPreviewHeading({ frontMatterYaml, slug }: { frontMatterYaml: string | null | undefined; slug: string }) {
  const { title, deck, blurb } = storyHeadings(frontMatterYaml, slug);
  return (
    <div className="newsroom-article-summary" data-newsroom-article-summary>
      <h2 className="newsroom-article-headline" data-newsroom-article-headline>{title}</h2>
      {deck ? <p className="newsroom-article-subtitle" data-newsroom-article-deck>{deck}</p> : null}
      {blurb ? <p className="newsroom-article-blurb" data-newsroom-article-blurb>{blurb}</p> : null}
    </div>
  );
}
