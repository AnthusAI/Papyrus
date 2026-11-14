import type { AplDocument } from "../contracts";
import { APL_VERSION, IS_NOT_ROUND, IS_ROUND, SIZE_RESOURCES, themeRef, VIEWPORT_PROFILES_IMPORT } from "./support/shared";

export const FEED_DOCUMENT_ID = "feed";
/** The datasource name the feed binds to: `{ publication, theme, stories: [{ index, title, deck?, byline?, imageUrl? }] }`. */
export const FEED_DATASOURCE = "feedData";
/** The UserEvent `arguments[0]` a tapped card sends; `arguments[1]` is the story's index in the feed. */
export const OPEN_STORY_ARGUMENT = "openStory";

const colour = (key: Parameters<typeof themeRef>[1]) => themeRef(FEED_DATASOURCE, key);

function card(): Record<string, unknown> {
  return {
    type: "TouchWrapper",
    width: "@cardWidth",
    // The whole card is the touch target; Alexa also lets a person say "select" plus the card's ordinal.
    onPress: { type: "SendEvent", arguments: [OPEN_STORY_ARGUMENT, "${index}"] },
    item: {
      type: "Frame",
      width: "100%",
      height: "100%",
      backgroundColor: colour("surface"),
      borderRadius: "@radius",
      item: {
        type: "Container",
        width: "100%",
        height: "100%",
        items: [
          {
            type: "Container",
            when: "${data.imageUrl}",
            width: "100%",
            paddingLeft: "@gap",
            paddingRight: "@gap",
            paddingTop: "@gap",
            items: [{ type: "Image", source: "${data.imageUrl}", width: "100%", height: "@cardImageHeight", scale: "best-fill", borderRadius: "@radius" }],
          },
          {
            type: "Container",
            width: "100%",
            paddingLeft: "@gap",
            paddingRight: "@gap",
            paddingTop: "@gap",
            paddingBottom: "@gap",
            items: [
              { type: "Text", text: "${data.title}", color: colour("text"), fontSize: "@headlineSize", fontWeight: "700", maxLines: 4 },
              { type: "Text", when: "${data.deck}", text: "${data.deck}", color: colour("mutedText"), fontSize: "@deckSize", paddingTop: 8, maxLines: 4 },
            ],
          },
        ],
      },
    },
  };
}

const publicationHeader = {
  type: "Text",
  text: "${payload.feedData.publication}",
  color: colour("accent"),
  fontSize: "@publicationSize",
  fontWeight: "800",
  paddingBottom: "@gap",
  maxLines: 1,
};

/**
 * The feed: a publication header over a Sequence of story cards. Touching a card sends a UserEvent
 * (`["openStory", <index>]`). Landscape profiles scroll the cards sideways; the round hub scrolls them down the screen.
 */
export const feedDocument: AplDocument = {
  id: FEED_DOCUMENT_ID,
  document: {
    type: "APL",
    version: APL_VERSION,
    import: [VIEWPORT_PROFILES_IMPORT],
    resources: SIZE_RESOURCES,
    mainTemplate: {
      parameters: ["payload"],
      items: [
        {
          type: "Container",
          width: "100vw",
          height: "100vh",
          backgroundColor: colour("background"),
          padding: "@pad",
          items: [
            { ...publicationHeader, when: IS_NOT_ROUND },
            { ...publicationHeader, when: IS_ROUND, textAlign: "center", width: "100%" },
            {
              type: "Sequence",
              when: IS_NOT_ROUND,
              scrollDirection: "horizontal",
              width: "100%",
              grow: 1,
              data: "${payload.feedData.stories}",
              items: [{ ...card(), spacing: "@gap" }],
            },
            {
              type: "Sequence",
              when: IS_ROUND,
              scrollDirection: "vertical",
              width: "100%",
              grow: 1,
              data: "${payload.feedData.stories}",
              items: [{ ...card(), width: "100%", height: "auto", spacing: "@gap" }],
            },
          ],
        },
      ],
    },
  },
};
