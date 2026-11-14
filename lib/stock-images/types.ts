/**
 * Stock image sources for a Story's cover (initiative PPY-5c9e9a, epic PPY-a36ac3).
 *
 * A source finds candidates; the newsroom shows four at a time; a pick brings one into the site's own media storage through the editor's
 * existing image path, so public pages never load from the source. Only Wikimedia Commons exists today (`commons.ts`).
 */

/** What we know about one image's licence, taken from the source's own structured data. Never guessed. */
export type StockLicence = {
  /** A stable key from our allowed list: `public-domain`, `cc0`, `cc-by`. */
  kind: string;
  /** The licence as the source names it, for example `CC BY 4.0`. */
  name: string;
  /** The licence's address as the source gives it; null only for public domain and CC0 when the source gives none. */
  url: string | null;
};

export type StockCandidate = {
  /** The source's own identifier for the file (for Commons, the file title, `File:Name.jpg`). */
  id: string;
  /** Which source found it, for example `wikimedia-commons`. */
  source: string;
  sourceLabel: string;
  title: string;
  /** One line saying what it is, from the source's description; may be empty. */
  description: string;
  /** The creator as the source records it. Required: an image with no known creator is never offered. */
  creator: string;
  licence: StockLicence;
  /** The file's own page at the source (where the creator and licence are stated). */
  sourceUrl: string;
  /** The picture to show and to copy in: a scaled copy no wider than the source gives us. */
  imageUrl: string;
  width: number;
  height: number;
};

export type SearchInput = {
  target: string;
  /** Opaque, from the previous result; empty for the first four. */
  cursor: string;
  /** Ids already shown for this Story in this run; they never come back. */
  exclude: ReadonlySet<string>;
  count: number;
};

export type SearchResult = {
  candidates: StockCandidate[];
  /** Where the next four start; null when the source has no more for this target. */
  nextCursor: string | null;
};

/** The shape every source implements. Generated images later can implement the same two calls. */
export interface StockImageSource {
  readonly id: string;
  readonly label: string;
  /** Hosts the picture bytes may be copied from. Anything else is refused. */
  readonly imageHosts: readonly string[];
  search(input: SearchInput): Promise<SearchResult>;
  /** Looks one candidate up again by id, so the stored licence record is the source's current answer, not the browser's copy. Null when it is gone or no longer allowed. */
  lookup(id: string): Promise<StockCandidate | null>;
}

/** The stored record for a chosen image (front matter `coverImage`). */
export type CoverImageRecord = {
  source: string;
  sourceLabel: string;
  sourceUrl: string;
  title: string;
  creator: string;
  licence: string;
  licenceUrl: string | null;
  /** Where the copy lives in the site's media: the Story's `image` points here. */
  srcPath: string;
  pickedAt: string;
  /** The editor's opaque account id; never an address. */
  pickedBy: string | null;
};

export class SourceBusy extends Error {
  constructor(readonly retryAfterSeconds: number | null, message = "The image source is busy. Try again in a minute.") {
    super(message);
  }
}

export class SourceFailure extends Error {}
