/**
 * A page address that opens the References feed on choices of its own. The home page's "See all" for accepted References that still need a
 * person to capture them links to
 *   /newsroom/references?reviewed=accepted&captured=no&sort=newest&minStars=0
 * Parameters: `reviewed` (any, accepted, yes, no), `captured` (any, yes, no), `sort` (best, newest, quality), `minStars` (0, 3, 4, 5). Unknown values are
 * ignored, and a choice the address does not name stays as the viewer saved it. These are a view for one visit and are never saved.
 */
import { FEED_CAPTURED, FEED_MIN_STARS, type FeedCaptured, type FeedMinStars, type FeedShow, type FeedSort } from "./reference-feed-ranking";

export type FeedViewChoices = { sort?: FeedSort; show?: FeedShow; minStars?: FeedMinStars; captured?: FeedCaptured };

const REVIEWED: Record<string, FeedShow> = { any: "all", accepted: "accepted", yes: "rated", no: "unrated" };
const SORTS: readonly FeedSort[] = ["best", "newest", "quality"];

/** The choices a location's query string names, or null when it names none. */
export function feedChoicesFromSearch(search: string): FeedViewChoices | null {
  const params = new URLSearchParams(search);
  const choices: FeedViewChoices = {};
  const reviewed = REVIEWED[params.get("reviewed") ?? ""];
  if (reviewed) choices.show = reviewed;
  const captured = params.get("captured");
  if ((FEED_CAPTURED as readonly string[]).includes(captured ?? "")) choices.captured = captured as FeedCaptured;
  const sort = params.get("sort");
  if ((SORTS as readonly string[]).includes(sort ?? "")) choices.sort = sort as FeedSort;
  const stars = params.get("minStars");
  if (stars !== null && (FEED_MIN_STARS as readonly number[]).includes(Number(stars))) choices.minStars = Number(stars) as FeedMinStars;
  return Object.keys(choices).length ? choices : null;
}

/** The address of the feed opened on every accepted Reference we could not capture, newest first. Not Quality, which lists only the starred ones. */
export const CAPTURE_NEEDED_FEED_PATH = "/newsroom/references?reviewed=accepted&captured=no&sort=newest&minStars=0";
