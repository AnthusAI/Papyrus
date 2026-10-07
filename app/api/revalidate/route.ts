import { toPublicReaderPath } from "../../../lib/reader-base-path";
import { revalidatePath, revalidateTag } from "next/cache";
import { NextResponse } from "next/server";
import {
  ARCHIVE_CACHE_TAG,
  ARTICLES_CACHE_TAG,
  EDITIONS_CACHE_TAG,
  articleCacheTag,
  editionContentCacheTag,
  editionItemCacheTag,
} from "../../../lib/cached-content-repository";
import { getEditionArticlePath, getEditionDatePath } from "../../../lib/edition-routes";

export const dynamic = "force-dynamic";

type RevalidateRequestBody = {
  editionDate?: string;
  articleSlugs?: string[];
  itemSlugs?: string[];
  paths?: string[];
  tags?: string[];
};

export async function POST(request: Request) {
  const configuredSecret = process.env.PAPYRUS_REVALIDATE_SECRET?.trim();
  const providedSecret = request.headers.get("x-papyrus-revalidate-secret")?.trim();
  if (!configuredSecret || providedSecret !== configuredSecret) {
    return NextResponse.json({ ok: false, error: "Unauthorized." }, { status: 401 });
  }

  const body = (await request.json()) as RevalidateRequestBody;
  const revalidatedTags = new Set<string>();
  const revalidatedPaths = new Set<string>();

  const editionDate = body.editionDate?.trim();
  if (editionDate) {
    revalidateTag(editionContentCacheTag(editionDate));
    revalidatedTags.add(editionContentCacheTag(editionDate));
    revalidatePath(getEditionDatePath(editionDate));
    revalidatedPaths.add(getEditionDatePath(editionDate));
  }

  for (const slug of body.articleSlugs ?? []) {
    const normalized = slug.trim();
    if (!normalized) continue;
    revalidateTag(articleCacheTag(normalized));
    revalidatedTags.add(articleCacheTag(normalized));
    revalidatePath(toPublicReaderPath(`/articles/${encodeURIComponent(normalized)}`));
    revalidatedPaths.add(toPublicReaderPath(`/articles/${encodeURIComponent(normalized)}`));
    if (editionDate) {
      revalidateTag(editionItemCacheTag(editionDate, normalized));
      revalidatedTags.add(editionItemCacheTag(editionDate, normalized));
      revalidatePath(getEditionArticlePath(editionDate, normalized));
      revalidatedPaths.add(getEditionArticlePath(editionDate, normalized));
    }
  }

  for (const slug of body.itemSlugs ?? []) {
    const normalized = slug.trim();
    if (!normalized || !editionDate) continue;
    revalidateTag(editionItemCacheTag(editionDate, normalized));
    revalidatedTags.add(editionItemCacheTag(editionDate, normalized));
    revalidatePath(getEditionArticlePath(editionDate, normalized));
    revalidatedPaths.add(getEditionArticlePath(editionDate, normalized));
  }

  for (const tag of body.tags ?? []) {
    const normalized = tag.trim();
    if (!normalized) continue;
    revalidateTag(normalized);
    revalidatedTags.add(normalized);
  }

  revalidateTag(EDITIONS_CACHE_TAG);
  revalidatedTags.add(EDITIONS_CACHE_TAG);
  revalidateTag(ARCHIVE_CACHE_TAG);
  revalidatedTags.add(ARCHIVE_CACHE_TAG);
  revalidateTag(ARTICLES_CACHE_TAG);
  revalidatedTags.add(ARTICLES_CACHE_TAG);
  revalidatePath(toPublicReaderPath("/archive"));
  revalidatedPaths.add(toPublicReaderPath("/archive"));

  for (const path of body.paths ?? []) {
    const normalized = path.trim();
    if (!normalized.startsWith("/")) continue;
    revalidatePath(normalized);
    revalidatedPaths.add(normalized);
  }

  return NextResponse.json({
    ok: true,
    revalidatedTags: [...revalidatedTags],
    revalidatedPaths: [...revalidatedPaths],
  });
}
