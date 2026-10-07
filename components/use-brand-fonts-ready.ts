"use client";

import { useEffect, useState } from "react";
import { listBrandFontFamilies } from "../lib/brand-fonts";
import { SITE_BRAND } from "../lib/site-brand";

/**
 * Returns a number that increments once the brand's declared font families
 * have loaded, so Pretext measurements taken with fallback metrics are
 * re-run with the real glyph widths. Stays 0 for brands without a font slot.
 */
export function useBrandFontsReadyVersion(): number {
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const families = listBrandFontFamilies(SITE_BRAND.fonts);
    if (families.length === 0 || !document.fonts) return;
    let isCancelled = false;
    void Promise.all(families.map((family) => document.fonts.load(`16px ${JSON.stringify(family)}`)))
      .then(() => document.fonts.ready)
      .then(() => {
        if (!isCancelled) setVersion((current) => current + 1);
      })
      .catch(() => undefined);
    return () => {
      isCancelled = true;
    };
  }, []);

  return version;
}
