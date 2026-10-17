"use client";

import { useEffect, useState } from "react";
import { listBrandFontFamilies } from "../lib/brand-fonts";
import { watchBrandFontsLoaded } from "../lib/brand-fonts-watch";
import { clearPretextMeasurementCache } from "../lib/pretext-layout";
import { SITE_BRAND } from "../lib/site-brand";

/**
 * Returns a number that increments each time the brand's declared font
 * families finish loading. Pretext's width cache is cleared first, so
 * measurements taken with fallback metrics are re-run with the real glyph
 * widths. Stays 0 for brands without a font slot, and on the server.
 */
export function useBrandFontsReadyVersion(): number {
  const [version, setVersion] = useState(0);

  useEffect(() => {
    return watchBrandFontsLoaded({
      fontFaceSet: typeof document === "undefined" ? undefined : document.fonts,
      families: listBrandFontFamilies(SITE_BRAND.fonts),
      clearMeasurementCaches: clearPretextMeasurementCache,
      onFontsSettled: () => setVersion((current) => current + 1),
    });
  }, []);

  return version;
}
