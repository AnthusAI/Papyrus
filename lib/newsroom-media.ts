export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export const IMAGE_CONTENT_TYPES: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  avif: "image/avif",
  svg: "image/svg+xml",
};

export type ImageFileLike = { name: string; size: number };

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot + 1).toLowerCase();
}

export function contentTypeForFilename(filename: string): string | null {
  return IMAGE_CONTENT_TYPES[extensionOf(filename)] ?? null;
}

export function isSvgFilename(filename: string): boolean {
  return extensionOf(filename) === "svg";
}

function sanitizeSegment(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^[-.]+|-+$/g, "");
}

export function srcPathFor(slug: string, filename: string, existingSrcPaths: Iterable<string> = []): string {
  const taken = new Set(existingSrcPaths);
  const extension = sanitizeSegment(extensionOf(filename));
  const dot = filename.lastIndexOf(".");
  const rawStem = dot === -1 ? filename : filename.slice(0, dot);
  const stem = sanitizeSegment(rawStem) || "image";
  const directory = sanitizeSegment(slug) || "article";
  const suffix = extension ? `.${extension}` : "";
  let candidate = `assets/${directory}/${stem}${suffix}`;
  for (let counter = 2; taken.has(candidate); counter += 1) {
    candidate = `assets/${directory}/${stem}-${counter}${suffix}`;
  }
  return candidate;
}

export async function sha256Hex(data: string | ArrayBuffer): Promise<string> {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function mediaIdFor(itemId: string, srcPath: string): Promise<string> {
  return `media-${itemId}-${(await sha256Hex(srcPath)).slice(0, 10)}`;
}

export function validateImageFile(file: ImageFileLike): string | null {
  if (contentTypeForFilename(file.name) === null) {
    return "Choose a PNG, JPEG, GIF, WebP, AVIF or SVG image.";
  }
  if (file.size <= 0) return "That file is empty.";
  if (file.size > MAX_IMAGE_BYTES) return "Images can be at most 10 MB.";
  return null;
}

function altAttributeValue(alt: string): string {
  return alt.replace(/[\r\n]+/g, " ").replace(/"/g, "'").replace(/[{}]/g, "");
}

export function imageDirective(srcPath: string, alt: string): string {
  return `::image{src="${srcPath}" alt="${altAttributeValue(alt)}" layout="inline"}`;
}

export type MediaAssetFields = {
  id: string;
  itemId: string;
  type: "image";
  role: "body";
  sortKey: string;
  storagePath: string;
  alt: string;
  width?: number;
  height?: number;
  metadata: string;
};

export function mediaSortKey(position: number, srcPath: string): string {
  return `${String(position).padStart(3, "0")}#${srcPath}`;
}

export type SelectionInsertion = { body: string; altSelectionStart: number };

function countEdgeNewlines(text: string, fromEnd: boolean): number {
  let count = 0;
  while (count < 2 && (fromEnd ? text[text.length - 1 - count] : text[count]) === "\n") count += 1;
  return count;
}

export function insertDirectiveAtSelection(
  body: string,
  selectionStart: number,
  selectionEnd: number,
  directive: string,
): SelectionInsertion {
  const before = body.slice(0, selectionStart);
  const after = body.slice(selectionEnd);
  const prefix = before === "" ? "" : "\n".repeat(2 - countEdgeNewlines(before, true));
  const suffix = after === "" ? "\n" : "\n".repeat(2 - countEdgeNewlines(after, false));
  const directiveStart = before.length + prefix.length;
  return {
    body: `${before}${prefix}${directive}${suffix}${after}`,
    altSelectionStart: directiveStart + directive.indexOf('alt="') + 'alt="'.length,
  };
}

export type MediaAssetRecord = {
  id: string;
  sortKey: string;
  storagePath: string | null;
  alt: string;
  srcPath: string | null;
};

export type NewsroomMediaBackend = {
  uploadImage: (input: { storagePath: string; data: Blob; contentType: string }) => Promise<void>;
  createMediaAsset: (fields: MediaAssetFields) => Promise<void>;
  listMediaAssets: (itemId: string) => Promise<MediaAssetRecord[]>;
  imageUrl: (storagePath: string) => Promise<string>;
};

export type ImageDimensionReader = (file: Blob, filename: string) => Promise<{ width: number; height: number } | null>;

export type UploadedImage = { srcPath: string; directive: string; imageUrl: string };

export async function uploadArticleImage(
  backend: NewsroomMediaBackend,
  readDimensions: ImageDimensionReader,
  input: { itemId: string; slug: string; file: File },
): Promise<UploadedImage> {
  const problem = validateImageFile(input.file);
  if (problem) throw new Error(problem);
  const contentType = contentTypeForFilename(input.file.name) as string;
  const existing = await backend.listMediaAssets(input.itemId);
  const srcPath = srcPathFor(
    input.slug,
    input.file.name,
    existing.map((asset) => asset.srcPath).filter((path): path is string => path !== null),
  );
  const bytes = await input.file.arrayBuffer();
  const sha256 = await sha256Hex(bytes);
  const dimensions = await readDimensions(input.file, input.file.name);
  const storagePath = `media/${srcPath}`;
  await backend.uploadImage({ storagePath, data: input.file, contentType });
  await backend.createMediaAsset({
    id: await mediaIdFor(input.itemId, srcPath),
    itemId: input.itemId,
    type: "image",
    role: "body",
    sortKey: mediaSortKey(existing.length + 1, srcPath),
    storagePath,
    alt: input.file.name,
    ...(dimensions ?? {}),
    metadata: JSON.stringify({ srcPath, sha256, bytes: bytes.byteLength, contentType }),
  });
  return { srcPath, directive: imageDirective(srcPath, ""), imageUrl: await backend.imageUrl(storagePath) };
}

export async function readImageDimensions(file: Blob, filename: string): Promise<{ width: number; height: number } | null> {
  if (isSvgFilename(filename)) return null;
  try {
    const bitmap = await createImageBitmap(file);
    const size = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return size;
  } catch {
    return null;
  }
}
