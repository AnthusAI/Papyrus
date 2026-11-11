// What the attachment upload accepts for the visual style profile's example pictures (design: project/wiki/image-toolchain.md section 5.8).
// Pure rules with no AWS in them, so a test can run them without a backend. The handler applies them next to its general checks.

export const VISUAL_ROLES = new Set(["visual_example", "visual_negative"]);
// The profile is one Item lineage; the examples are owned by it, not by one of its versions, so the same picture is one row however often the profile changes.
export const VISUAL_STYLE_OWNER_ID = "item-editorial-doctrine-visual-style";
export const VISUAL_STYLE_SLUG = "editorial-doctrine-visual-style";
export const MAX_VISUAL_BYTES = 10 * 1024 * 1024; // the newsroom editor's own MAX_IMAGE_BYTES; the general cap is 25 MB
// Providers take raster images, so SVG is not accepted.
export const VISUAL_MEDIA_TYPES: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" };

export function isVisualRole(role: string): boolean {
  return VISUAL_ROLES.has(role);
}

export type VisualInput = { ownerKind: string; ownerId: string; role: string; mediaType: string; byteSize: number; sha256: string | null; sortKey: string; filename: string };

/** Throws a plain-words error when a visual role's upload breaks a rule. Other roles are not touched here. */
export function assertVisualUpload(input: VisualInput): void {
  if (input.ownerKind !== "item" || input.ownerId !== VISUAL_STYLE_OWNER_ID) {
    throw new Error(`Example pictures belong to the visual style profile (item ${VISUAL_STYLE_OWNER_ID}).`);
  }
  if (!(input.mediaType in VISUAL_MEDIA_TYPES)) throw new Error("Example pictures must be PNG, JPEG or WebP.");
  if (input.byteSize > MAX_VISUAL_BYTES) throw new Error("Example pictures must be 10 MB or smaller.");
  if (!input.sha256) throw new Error("Example pictures need a sha256, which names the stored file so the same picture is kept once.");
  if (input.sortKey !== input.sha256) throw new Error("An example picture's sortKey must be its sha256.");
  const expected = `${input.sha256}.${VISUAL_MEDIA_TYPES[input.mediaType]}`;
  if (input.filename !== expected) throw new Error(`An example picture's filename must be ${expected}.`);
}

/** The image media types are for the visual roles only; no other role may start taking pictures. */
export function mediaTypeAllowedForRole(role: string, mediaType: string, generalTypes: Set<string>): boolean {
  return isVisualRole(role) ? mediaType in VISUAL_MEDIA_TYPES : generalTypes.has(mediaType);
}

/** Image file sizes have their own cap; every other role keeps the general one. */
export function byteLimitForRole(role: string, general: number): number {
  return isVisualRole(role) ? MAX_VISUAL_BYTES : general;
}
