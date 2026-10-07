export type SiteBrandFontFace = {
  /** Public URL of the font file, e.g. `/fonts/acme-serif-regular.woff2`. */
  src: string;
  weight?: number | string;
  style?: "normal" | "italic";
};

export type SiteBrandGoogleFontSource = {
  weights: number[];
  /** Also load the italic style of every listed weight. */
  italics?: boolean;
};

/**
 * One brand-declared font family. Declare exactly one source: `google` loads
 * the family from the Google Fonts stylesheet API; `faces` self-hosts files
 * with `@font-face`. The root layout exposes `cssVariable` as
 * `"<family>", <fallback>` on `<html>`, so publication CSS writes
 * `font-family: var(--font-masthead)`.
 */
export type SiteBrandFont = {
  family: string;
  cssVariable: string;
  fallback?: string;
  google?: SiteBrandGoogleFontSource;
  faces?: SiteBrandFontFace[];
};

export type BrandFontAssets = {
  preconnectOrigins: string[];
  stylesheetHrefs: string[];
  fontFaceCss: string;
  rootStyle: Record<string, string>;
  isEmpty: boolean;
};

const GOOGLE_STYLESHEET_ORIGIN = "https://fonts.googleapis.com";
const GOOGLE_FILE_ORIGIN = "https://fonts.gstatic.com";
const DEFAULT_FALLBACK = "sans-serif";
const CSS_VARIABLE_PATTERN = /^--[a-z][a-z0-9-]*$/;

export function validateBrandFonts(fonts: SiteBrandFont[]): void {
  const seenVariables = new Set<string>();
  for (const font of fonts) {
    if (!font.family.trim()) throw new Error("A brand font needs a family name.");
    if (!CSS_VARIABLE_PATTERN.test(font.cssVariable)) {
      throw new Error(`Brand font "${font.family}" cssVariable must look like --font-name, got "${font.cssVariable}".`);
    }
    if (seenVariables.has(font.cssVariable)) {
      throw new Error(`Brand font cssVariable ${font.cssVariable} is declared twice.`);
    }
    seenVariables.add(font.cssVariable);
    const sourceCount = Number(Boolean(font.google)) + Number(Boolean(font.faces?.length));
    if (sourceCount !== 1) {
      throw new Error(`Brand font "${font.family}" must declare exactly one source: google or faces.`);
    }
    if (font.google && font.google.weights.length === 0) {
      throw new Error(`Brand font "${font.family}" google source needs at least one weight.`);
    }
  }
}

function buildGoogleFamilyQuery(font: SiteBrandFont): string {
  const google = font.google!;
  const weights = [...new Set(google.weights)].sort((left, right) => left - right);
  const familyName = font.family.trim().replace(/\s+/g, "+");
  if (!google.italics) return `family=${familyName}:wght@${weights.join(";")}`;
  const axisValues = [0, 1].flatMap((italic) => weights.map((weight) => `${italic},${weight}`));
  return `family=${familyName}:ital,wght@${axisValues.join(";")}`;
}

export function buildGoogleFontsHref(fonts: SiteBrandFont[]): string | null {
  const googleFonts = fonts.filter((font) => font.google);
  if (googleFonts.length === 0) return null;
  return `${GOOGLE_STYLESHEET_ORIGIN}/css2?${googleFonts.map(buildGoogleFamilyQuery).join("&")}&display=swap`;
}

function buildFontFaceCss(font: SiteBrandFont): string {
  return (font.faces ?? [])
    .map((face) => {
      const declarations = [
        `font-family:${JSON.stringify(font.family)}`,
        `src:url(${JSON.stringify(face.src)})`,
        `font-weight:${face.weight ?? 400}`,
        `font-style:${face.style ?? "normal"}`,
        "font-display:swap",
      ];
      return `@font-face{${declarations.join(";")}}`;
    })
    .join("");
}

export function resolveBrandFontAssets(fonts: SiteBrandFont[] | undefined): BrandFontAssets {
  if (!fonts || fonts.length === 0) {
    return { preconnectOrigins: [], stylesheetHrefs: [], fontFaceCss: "", rootStyle: {}, isEmpty: true };
  }
  validateBrandFonts(fonts);
  const googleHref = buildGoogleFontsHref(fonts);
  return {
    preconnectOrigins: googleHref ? [GOOGLE_STYLESHEET_ORIGIN, GOOGLE_FILE_ORIGIN] : [],
    stylesheetHrefs: googleHref ? [googleHref] : [],
    fontFaceCss: fonts.map(buildFontFaceCss).join(""),
    rootStyle: Object.fromEntries(
      fonts.map((font) => [font.cssVariable, `${JSON.stringify(font.family)}, ${font.fallback ?? DEFAULT_FALLBACK}`]),
    ),
    isEmpty: false,
  };
}

export function listBrandFontFamilies(fonts: SiteBrandFont[] | undefined): string[] {
  return (fonts ?? []).map((font) => font.family);
}
