import { PICTURE_FORMATS } from "./picture";
import type { StockCandidate } from "./types";

/** What the picker needs from a source, wherever it runs. The live one calls the editor-only route; the preview one makes up pictures. */
export type StockImageClient = {
  search(input: { target: string; cursor: string; exclude: string[] }): Promise<{ candidates: StockCandidate[]; nextCursor: string | null }>;
  /** Looks the pick up again at the source and copies its bytes, ready for the editor's own image upload. */
  fetchPicked(candidate: StockCandidate): Promise<{ candidate: StockCandidate; file: File; pickedBy: string | null }>;
};

export const STOCK_IMAGE_ROUTE = "/api/newsroom/stock-images";

export class StockImageError extends Error {}

type Authorise = () => Promise<string | null>;
type Fetcher = typeof fetch;

function slugFor(title: string): string {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "image";
}

async function messageOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    if (body.error) return body.error;
  } catch {
    // fall through
  }
  return response.status === 401 ? "Sign in again as an editor." : `The request failed (${response.status}).`;
}

export function createLiveStockImageClient(authorise: Authorise, fetcher: Fetcher = (input, init) => globalThis.fetch(input, init)): StockImageClient {
  async function post(body: Record<string, unknown>): Promise<Response> {
    const token = await authorise();
    if (!token) throw new StockImageError("Sign in again as an editor.");
    let response: Response;
    try {
      response = await fetcher(STOCK_IMAGE_ROUTE, {
        method: "POST",
        headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
        body: JSON.stringify(body),
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch {
      throw new StockImageError("The newsroom could not be reached. Check your connection and try again.");
    }
    if (!response.ok) throw new StockImageError(await messageOf(response));
    return response;
  }
  return {
    async search({ target, cursor, exclude }) {
      const body = (await (await post({ action: "search", target, cursor, exclude })).json()) as { candidates?: StockCandidate[]; nextCursor?: string | null };
      return { candidates: body.candidates ?? [], nextCursor: body.nextCursor ?? null };
    },
    async fetchPicked(candidate) {
      const looked = (await (await post({ action: "lookup", id: candidate.id })).json()) as { candidate: StockCandidate };
      const response = await post({ action: "image", id: candidate.id });
      const mediaType = (response.headers.get("content-type") ?? "").split(";")[0];
      const format = Object.values(PICTURE_FORMATS).find((one) => one.mediaType === mediaType);
      if (!format) throw new StockImageError("The copied file was not a picture we accept.");
      const blob = await response.blob();
      const file = new File([blob], `${slugFor(looked.candidate.title)}.${format.extension}`, { type: format.mediaType });
      return { candidate: looked.candidate, file, pickedBy: response.headers.get("x-stock-picked-by") };
    },
  };
}

export async function accessTokenFromAmplify(): Promise<string | null> {
  const { fetchAuthSession } = await import("aws-amplify/auth");
  const session = await fetchAuthSession();
  return session.tokens?.accessToken?.toString() ?? null;
}
