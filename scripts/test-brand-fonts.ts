import assert from "node:assert/strict";
import { buildGoogleFontsHref, resolveBrandFontAssets, validateBrandFonts, type SiteBrandFont } from "../lib/brand-fonts";

const mastheadFont: SiteBrandFont = {
  family: "Inter",
  cssVariable: "--font-masthead",
  fallback: "Helvetica, Arial, sans-serif",
  google: { weights: [900, 400, 700, 600] },
};
const bodyFont: SiteBrandFont = {
  family: "IBM Plex Serif",
  cssVariable: "--font-body",
  fallback: "Georgia, serif",
  google: { weights: [400, 600], italics: true },
};
const selfHostedFont: SiteBrandFont = {
  family: "Acme Display",
  cssVariable: "--font-display",
  faces: [
    { src: "/fonts/acme-display-regular.woff2" },
    { src: "/fonts/acme-display-bold-italic.woff2", weight: 700, style: "italic" },
  ],
};

const emptyAssets = resolveBrandFontAssets(undefined);
assert.equal(emptyAssets.isEmpty, true);
assert.deepEqual(emptyAssets.rootStyle, {});
assert.deepEqual(emptyAssets.stylesheetHrefs, []);
assert.equal(resolveBrandFontAssets([]).isEmpty, true);

assert.equal(
  buildGoogleFontsHref([mastheadFont, bodyFont]),
  "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&family=IBM+Plex+Serif:ital,wght@0,400;0,600;1,400;1,600&display=swap",
);
assert.equal(buildGoogleFontsHref([selfHostedFont]), null);

const googleAssets = resolveBrandFontAssets([mastheadFont, bodyFont]);
assert.equal(googleAssets.isEmpty, false);
assert.deepEqual(googleAssets.preconnectOrigins, ["https://fonts.googleapis.com", "https://fonts.gstatic.com"]);
assert.equal(googleAssets.stylesheetHrefs.length, 1);
assert.equal(googleAssets.fontFaceCss, "");
assert.deepEqual(googleAssets.rootStyle, {
  "--font-masthead": '"Inter", Helvetica, Arial, sans-serif',
  "--font-body": '"IBM Plex Serif", Georgia, serif',
});

const selfHostedAssets = resolveBrandFontAssets([selfHostedFont]);
assert.deepEqual(selfHostedAssets.preconnectOrigins, []);
assert.deepEqual(selfHostedAssets.stylesheetHrefs, []);
assert.equal(
  selfHostedAssets.fontFaceCss,
  '@font-face{font-family:"Acme Display";src:url("/fonts/acme-display-regular.woff2");font-weight:400;font-style:normal;font-display:swap}' +
    '@font-face{font-family:"Acme Display";src:url("/fonts/acme-display-bold-italic.woff2");font-weight:700;font-style:italic;font-display:swap}',
);
assert.deepEqual(selfHostedAssets.rootStyle, { "--font-display": '"Acme Display", sans-serif' });

assert.throws(() => validateBrandFonts([{ family: "No Source", cssVariable: "--font-none" }]), /exactly one source/);
assert.throws(
  () => validateBrandFonts([{ ...mastheadFont, faces: selfHostedFont.faces }]),
  /exactly one source/,
);
assert.throws(() => validateBrandFonts([{ ...mastheadFont, cssVariable: "font-masthead" }]), /cssVariable must look like/);
assert.throws(() => validateBrandFonts([mastheadFont, { ...bodyFont, cssVariable: "--font-masthead" }]), /declared twice/);
assert.throws(() => validateBrandFonts([{ ...mastheadFont, google: { weights: [] } }]), /at least one weight/);

console.log("brand fonts ok");
