/**
 * Checking the bytes of a picture before it is copied in, the same checks `src/papyrus_content/reference_thumbnails.py` makes (`read_picture`):
 * a real picture of an accepted type, not empty, under a size ceiling, wide enough to be a cover and not a stand-in. The Python code uses
 * Pillow; here the type is read from the file's own first bytes and the size from its header, so nothing is trusted from a header or a name.
 */
export const MAXIMUM_PICTURE_BYTES = 4_500_000;
export const MINIMUM_PICTURE_WIDTH = 800;
export const PICTURE_FORMATS = {
  jpeg: { extension: "jpg", mediaType: "image/jpeg" },
  png: { extension: "png", mediaType: "image/png" },
  webp: { extension: "webp", mediaType: "image/webp" },
} as const;
export type PictureKind = keyof typeof PICTURE_FORMATS;
export type Picture = { kind: PictureKind; extension: string; mediaType: string; width: number; height: number; bytes: number };

export class PictureRefused extends Error {}

function ascii(bytes: Uint8Array, start: number, length: number): string {
  return String.fromCharCode(...bytes.subarray(start, start + length));
}

function jpegSize(bytes: Uint8Array): { width: number; height: number } | null {
  let at = 2;
  while (at + 9 < bytes.length) {
    if (bytes[at] !== 0xff) { at += 1; continue; }
    const marker = bytes[at + 1];
    if (marker === 0xff) { at += 1; continue; }
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) { at += 2; continue; }
    const length = (bytes[at + 2] << 8) | bytes[at + 3];
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { height: (bytes[at + 5] << 8) | bytes[at + 6], width: (bytes[at + 7] << 8) | bytes[at + 8] };
    }
    if (length < 2) return null;
    at += 2 + length;
  }
  return null;
}

function pngSize(bytes: Uint8Array): { width: number; height: number } | null {
  if (bytes.length < 24 || ascii(bytes, 12, 4) !== "IHDR") return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return { width: view.getUint32(16), height: view.getUint32(20) };
}

function webpSize(bytes: Uint8Array): { width: number; height: number } | null {
  if (bytes.length < 30) return null;
  const chunk = ascii(bytes, 12, 4);
  if (chunk === "VP8 ") return { width: (bytes[26] | (bytes[27] << 8)) & 0x3fff, height: (bytes[28] | (bytes[29] << 8)) & 0x3fff };
  if (chunk === "VP8L") {
    const bits = bytes[21] | (bytes[22] << 8) | (bytes[23] << 16) | (bytes[24] << 24);
    return { width: (bits & 0x3fff) + 1, height: ((bits >> 14) & 0x3fff) + 1 };
  }
  if (chunk === "VP8X") {
    return { width: 1 + (bytes[24] | (bytes[25] << 8) | (bytes[26] << 16)), height: 1 + (bytes[27] | (bytes[28] << 8) | (bytes[29] << 16)) };
  }
  return null;
}

/** The picture's type and size, or throws `PictureRefused` with a plain reason. */
export function readPicture(bytes: Uint8Array): Picture {
  if (bytes.length === 0) throw new PictureRefused("The image was empty.");
  if (bytes.length > MAXIMUM_PICTURE_BYTES) throw new PictureRefused("The image is too large to copy in.");
  let kind: PictureKind | null = null;
  let size: { width: number; height: number } | null = null;
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) { kind = "jpeg"; size = jpegSize(bytes); }
  else if (ascii(bytes, 1, 3) === "PNG" && bytes[0] === 0x89) { kind = "png"; size = pngSize(bytes); }
  else if (ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 4) === "WEBP") { kind = "webp"; size = webpSize(bytes); }
  if (!kind) throw new PictureRefused("That is not a JPEG, PNG or WebP picture.");
  if (!size || size.width <= 0 || size.height <= 0) throw new PictureRefused("The picture's size could not be read.");
  if (size.width < MINIMUM_PICTURE_WIDTH) throw new PictureRefused(`The picture is only ${size.width} px wide.`);
  return { kind, ...PICTURE_FORMATS[kind], ...size, bytes: bytes.length };
}
