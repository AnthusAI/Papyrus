import type { AplDocument } from "../contracts";
import { APL_VERSION, IS_NOT_ROUND, IS_ROUND, SIZE_RESOURCES, themeRef, VIEWPORT_PROFILES_IMPORT } from "./support/shared";

export const STORY_DOCUMENT_ID = "story";
/** The datasource name the story binds to: `{ title, meta, imageUrl?, paragraphs: string[], theme }`. */
export const STORY_DATASOURCE = "storyData";

const colour = (key: Parameters<typeof themeRef>[1]) => themeRef(STORY_DATASOURCE, key);

const title = { type: "Text", text: "${payload.storyData.title}", color: colour("text"), fontSize: "@headlineSize", fontWeight: "800", maxLines: 5 };
const meta = { type: "Text", when: "${payload.storyData.meta}", text: "${payload.storyData.meta}", color: colour("mutedText"), fontSize: "@metaSize", paddingTop: 8, paddingBottom: "@gap" };
// Paragraphs never shrink to the screen: the ScrollView scrolls them at full length (shrinking cut each one off with "…").
const body = {
  type: "Container",
  width: "100%",
  shrink: 0,
  data: "${payload.storyData.paragraphs}",
  items: [{ type: "Text", text: "${data}", width: "100%", shrink: 0, color: colour("text"), fontSize: "@bodySize", lineHeight: 1.4, paddingBottom: "@gap" }],
};

/**
 * The story: hero image, title, byline and date, and a scrolling body. Landscape profiles put the hero beside the text with only the
 * body scrolling; the round hub stacks everything in one scroll. The hero is left out when the story has no image.
 */
export const storyDocument: AplDocument = {
  id: STORY_DOCUMENT_ID,
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
          when: IS_NOT_ROUND,
          width: "100vw",
          height: "100vh",
          direction: "row",
          backgroundColor: colour("background"),
          padding: "@pad",
          items: [
            {
              type: "Image",
              when: "${payload.storyData.imageUrl}",
              source: "${payload.storyData.imageUrl}",
              width: "@heroWidth",
              height: "100%",
              scale: "best-fill",
              borderRadius: "@radius",
              paddingRight: "@gap",
            },
            {
              type: "Container",
              grow: 1,
              shrink: 1,
              height: "100%",
              paddingLeft: "@gap",
              items: [title, meta, { type: "ScrollView", grow: 1, shrink: 1, width: "100%", item: body }],
            },
          ],
        },
        {
          type: "Container",
          when: IS_ROUND,
          width: "100vw",
          height: "100vh",
          backgroundColor: colour("background"),
          paddingLeft: "@pad",
          paddingRight: "@pad",
          items: [
            {
              type: "ScrollView",
              width: "100%",
              height: "100%",
              item: {
                type: "Container",
                width: "100%",
                paddingTop: "@pad",
                paddingBottom: "@pad",
                items: [
                  { type: "Image", when: "${payload.storyData.imageUrl}", source: "${payload.storyData.imageUrl}", width: "100%", height: "@heroHeight", scale: "best-fill", borderRadius: "@radius", paddingBottom: "@gap" },
                  title,
                  meta,
                  body,
                ],
              },
            },
          ],
        },
      ],
    },
  },
};
