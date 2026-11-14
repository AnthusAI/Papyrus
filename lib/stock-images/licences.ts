import type { StockLicence } from "./types";

/**
 * Which licences a cover may carry, decided conservatively from Wikimedia's own documents (Commons:Licensing, Commons:Reusing content outside
 * Wikimedia, Commons:Credit line). Every image still gets a credit, whether or not its licence requires one (Ryan, 2026-11-05).
 *
 * Offered: public domain, CC0, and CC BY in any version (including the country ports). Each allows commercial use and adaptation (a resized or
 * cropped copy) with only credit and a licence link as conditions.
 *
 * NOT offered: CC BY-SA (all versions), and anything else (GFDL, Free Art, GPL, OGL, "attribution" tags with no version). Share-alike
 * requires an adaptation, which a resized or cropped cover is, to carry the same licence; whether our cover images can accept that is a
 * question for Ryan. Turning it on later is one line: `OFFER_SHARE_ALIKE`.
 *
 * Non-free, non-commercial, no-derivatives and unknown licences are refused outright.
 */
export const OFFER_SHARE_ALIKE = false;

const CC_BY = /^CC[ -]BY[ -](\d\.\d)(?: ([A-Za-z]{2,3}))?$/i;
const CC_BY_SA = /^CC[ -]BY[ -]SA[ -](\d\.\d)(?: ([A-Za-z]{2,3}))?$/i;
const CC0 = /^CC0(?: 1\.0)?(?: Universal)?$/i;
const PUBLIC_DOMAIN = /^public domain$/i;

export type LicenceFacts = {
  /** `LicenseShortName` from the API's extmetadata. */
  shortName: string | null;
  /** `LicenseUrl`. */
  url: string | null;
  /** `Copyrighted`: "True" or "False" when stated. */
  copyrighted: string | null;
};

function httpsUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/** The licence if the facts name an allowed one with what a credit needs; otherwise null. */
export function allowedLicence(facts: LicenceFacts): StockLicence | null {
  const name = (facts.shortName ?? "").replace(/\s+/g, " ").trim();
  if (!name) return null;
  const url = httpsUrl(facts.url);
  if (PUBLIC_DOMAIN.test(name)) {
    if ((facts.copyrighted ?? "").toLowerCase() === "true") return null;
    return { kind: "public-domain", name: "Public domain", url };
  }
  if (CC0.test(name)) return { kind: "cc0", name: "CC0", url };
  if (CC_BY.test(name)) {
    if (!url) return null;
    return { kind: "cc-by", name, url };
  }
  if (OFFER_SHARE_ALIKE && CC_BY_SA.test(name)) {
    if (!url) return null;
    return { kind: "cc-by-sa", name, url };
  }
  return null;
}

export const OFFERED_LICENCES_TEXT = OFFER_SHARE_ALIKE
  ? "public domain, CC0, CC BY and CC BY-SA"
  : "public domain, CC0 and CC BY";
