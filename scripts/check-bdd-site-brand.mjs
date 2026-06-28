#!/usr/bin/env node

const baseUrl = process.env.PAPYRUS_BASE_URL ?? "http://127.0.0.1:3001";
const requireCanonical = process.env.PAPYRUS_BDD_REQUIRE_CANONICAL_BRAND === "1";

function parseAttributes(html) {
  const read = (name) => html.match(new RegExp(`data-${name}="([^"]*)"`))?.[1] ?? null;
  return {
    siteBrand: read("site-brand"),
    defaultPresentation: read("default-presentation"),
    forcedPresentation: read("forced-presentation"),
    presentationChoices: (read("presentation-choices") ?? "")
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
  };
}

async function main() {
  let response;
  try {
    response = await fetch(baseUrl, { redirect: "follow" });
  } catch (error) {
    console.error(`Failed to reach ${baseUrl}: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }

  if (!response.ok) {
    console.error(`Expected ${baseUrl} to respond successfully; received HTTP ${response.status}`);
    process.exit(1);
  }

  const html = await response.text();
  const attributes = parseAttributes(html);
  const allowsPresentationChoice = attributes.presentationChoices.length > 1;
  const supportsNewspaper = attributes.presentationChoices.includes("newspaper");

  console.log(
    `BDD site profile: brand=${attributes.siteBrand ?? "unknown"} `
    + `default=${attributes.defaultPresentation ?? "unknown"} `
    + `forced=${attributes.forcedPresentation ?? "none"} `
    + `choices=${attributes.presentationChoices.join("|") || "none"}`,
  );

  if (!requireCanonical) {
    if (!supportsNewspaper) {
      console.log("Note: newspaper layout scenarios tagged @newspaper will skip on this site profile.");
    }
    if (!allowsPresentationChoice) {
      console.log("Note: presentation settings scenarios tagged @presentation-choice will skip on this site profile.");
    }
    return;
  }

  if (attributes.siteBrand !== "papyrus") {
    console.error(
      `Canonical BDD requires PAPYRUS_SITE_BRAND=papyrus on the running server; found ${attributes.siteBrand ?? "unknown"}. `
      + "Start the app with config/bdd-canonical.env.example or set NEXT_PUBLIC_PAPYRUS_SITE_BRAND=papyrus.",
    );
    process.exit(1);
  }

  if (!supportsNewspaper) {
    console.error("Canonical BDD requires newspaper presentation support on the running server.");
    process.exit(1);
  }

  if (!allowsPresentationChoice) {
    console.error("Canonical BDD requires unlocked presentation format choice on the running server.");
    process.exit(1);
  }

  console.log("Canonical BDD site profile verified.");
}

void main();
