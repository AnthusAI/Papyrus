/**
 * Pieces both APL documents share: the viewport profile package import, the per-profile sizes (as APL resources chosen with
 * `when`) and the profile conditions. Nothing here is a document; `apl/feed.ts` and `apl/story.ts` are.
 */

/** The APL viewport profiles the documents are laid out for. */
export const VIEWPORT_PROFILES = ["hubRoundSmall", "hubLandscapeSmall", "hubLandscapeMedium", "hubLandscapeLarge", "tvLandscapeXLarge"] as const;
export type ViewportProfile = (typeof VIEWPORT_PROFILES)[number];

/** The lowest APL version the documents need (Frame borderRadius, resources, `when`, ScrollView). */
export const APL_VERSION = "2023.3";

export const VIEWPORT_PROFILES_IMPORT = { name: "alexa-viewport-profiles", version: "1.6.0" } as const;

export function profileIs(profile: ViewportProfile): string {
  return `\${@viewportProfile == @${profile}}`;
}

export const IS_ROUND = profileIs("hubRoundSmall");
export const IS_NOT_ROUND = `\${@viewportProfile != @hubRoundSmall}`;

type Sizes = {
  /** Safe-area padding around the screen, in dp. TVs overscan, so they get more. */
  pad: number;
  gap: number;
  publicationSize: number;
  headlineSize: number;
  deckSize: number;
  bodySize: number;
  metaSize: number;
  /** Feed card width and card image height. */
  cardWidth: number;
  cardImageHeight: number;
  /** Story hero width (landscape) or height (round). */
  heroWidth: number;
  heroHeight: number;
  radius: number;
};

// Sizes are in dp. Body text is at least 18dp on a hub and 26dp on a TV (viewed from across the room); every size stays well above
// the 14dp floor in the Alexa visual design guidance.
const SIZES: Record<ViewportProfile, Sizes> = {
  hubRoundSmall: { pad: 48, gap: 12, publicationSize: 24, headlineSize: 26, deckSize: 20, bodySize: 22, metaSize: 18, cardWidth: 384, cardImageHeight: 150, heroWidth: 384, heroHeight: 170, radius: 20 },
  hubLandscapeSmall: { pad: 24, gap: 16, publicationSize: 28, headlineSize: 26, deckSize: 20, bodySize: 22, metaSize: 18, cardWidth: 360, cardImageHeight: 150, heroWidth: 340, heroHeight: 200, radius: 20 },
  hubLandscapeMedium: { pad: 32, gap: 20, publicationSize: 32, headlineSize: 30, deckSize: 22, bodySize: 24, metaSize: 20, cardWidth: 400, cardImageHeight: 220, heroWidth: 400, heroHeight: 240, radius: 24 },
  hubLandscapeLarge: { pad: 40, gap: 24, publicationSize: 36, headlineSize: 34, deckSize: 24, bodySize: 26, metaSize: 22, cardWidth: 520, cardImageHeight: 300, heroWidth: 520, heroHeight: 300, radius: 28 },
  tvLandscapeXLarge: { pad: 56, gap: 24, publicationSize: 40, headlineSize: 36, deckSize: 28, bodySize: 30, metaSize: 26, cardWidth: 480, cardImageHeight: 220, heroWidth: 440, heroHeight: 260, radius: 28 },
};

/** One `when` resource block per profile, then an unconditional default (the medium hub) for any other viewport. */
export const SIZE_RESOURCES = [
  ...VIEWPORT_PROFILES.map((profile) => ({ when: profileIs(profile), dimensions: SIZES[profile] })),
  { dimensions: SIZES.hubLandscapeMedium },
];

export function sizesFor(profile: ViewportProfile): Sizes {
  return SIZES[profile];
}

/** Colours are datasource values, so the same document serves any site theme: `${payload.<source>.theme.<key>}`. */
export function themeRef(source: string, key: "background" | "surface" | "text" | "mutedText" | "accent"): string {
  return `\${payload.${source}.theme.${key}}`;
}
