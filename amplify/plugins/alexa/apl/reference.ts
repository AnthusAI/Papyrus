import type { AplDocument } from "../contracts";
import { APL_VERSION, IS_NOT_ROUND, IS_ROUND, SIZE_RESOURCES, themeRef, VIEWPORT_PROFILES_IMPORT } from "./support/shared";

export const REFERENCE_DOCUMENT_ID = "reference";
/** `{ queueLabel, title, meta, deck?, summary?, theme }`, built by `review/card.ts`. */
export const REFERENCE_DATASOURCE = "referenceData";
/** A touched button sends `["review", "accept" | "reject" | "skip"]`; the same actions as saying them. */
export const REVIEW_EVENT_ARGUMENT = "review";

const colour = (key: Parameters<typeof themeRef>[1]) => themeRef(REFERENCE_DATASOURCE, key);
const data = (field: string) => `\${payload.${REFERENCE_DATASOURCE}.${field}}`;

const queueLabel = { type: "Text", text: data("queueLabel"), color: colour("accent"), fontSize: "@metaSize", fontWeight: "700", paddingBottom: 8 };
const title = { type: "Text", text: data("title"), color: colour("text"), fontSize: "@headlineSize", fontWeight: "800", maxLines: 4 };
const meta = { type: "Text", when: data("meta"), text: data("meta"), color: colour("mutedText"), fontSize: "@metaSize", paddingTop: 8 };
const deck = { type: "Text", when: data("deck"), text: data("deck"), color: colour("text"), fontSize: "@deckSize", fontWeight: "600", paddingTop: "@gap", width: "100%", shrink: 0 };
const summary = { type: "Text", when: data("summary"), text: data("summary"), color: colour("text"), fontSize: "@bodySize", lineHeight: 1.4, paddingTop: "@gap", width: "100%", shrink: 0 };

/** A button is a flat rounded fill with a word on it: the word carries the meaning, never the colour. */
function button(label: string, action: "accept" | "reject" | "skip") {
  return {
    type: "TouchWrapper",
    grow: 1,
    onPress: { type: "SendEvent", arguments: [REVIEW_EVENT_ARGUMENT, action] },
    item: {
      type: "Frame",
      backgroundColor: colour("surface"),
      borderRadius: "@radius",
      paddingTop: 14,
      paddingBottom: 14,
      item: { type: "Text", text: label, color: colour("text"), fontSize: "@deckSize", fontWeight: "700", textAlign: "center", width: "100%" },
    },
  };
}

const spacer = { type: "Container", width: "@gap" };
const buttons = {
  type: "Container",
  direction: "row",
  width: "100%",
  paddingTop: "@gap",
  items: [button("Accept", "accept"), spacer, button("Reject", "reject"), spacer, button("Skip", "skip")],
};

/**
 * One Reference under review: which list and where in it, the title, source and date, the subtitle, the summary (scrolling), and
 * Accept / Reject / Skip buttons. Landscape keeps the buttons fixed at the bottom; the round hub scrolls everything.
 */
export const referenceDocument: AplDocument = {
  id: REFERENCE_DOCUMENT_ID,
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
          backgroundColor: colour("background"),
          padding: "@pad",
          items: [
            queueLabel,
            title,
            meta,
            { type: "ScrollView", grow: 1, shrink: 1, width: "100%", item: { type: "Container", width: "100%", shrink: 0, items: [deck, summary] } },
            buttons,
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
              item: { type: "Container", width: "100%", paddingTop: "@pad", paddingBottom: "@pad", items: [queueLabel, title, meta, deck, summary, buttons] },
            },
          ],
        },
      ],
    },
  },
};
