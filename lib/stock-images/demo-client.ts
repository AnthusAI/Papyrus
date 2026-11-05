import type { StockImageClient } from "./client";
import type { StockCandidate } from "./types";

/** The picker's source in the seeded local preview and tests: invented pictures and credits, no network. Nothing here is a real image or creator. */
const SUBJECTS = ["Harbour at dawn", "Wind turbines", "Server room", "Market stall", "Railway bridge", "Lecture hall", "Solar roof", "Night street", "Coastline", "Laboratory bench", "Mountain road", "City library"];
const HUES = [12, 38, 160, 200, 262, 320];

function picture(label: string, hue: number): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960" viewBox="0 0 1280 960"><rect width="1280" height="960" fill="hsl(${hue} 35% 62%)"/><rect y="560" width="1280" height="400" fill="hsl(${hue} 30% 42%)"/><text x="64" y="120" font-family="sans-serif" font-size="72" fill="white">${label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export function demoCandidate(index: number): StockCandidate {
  const subject = SUBJECTS[index % SUBJECTS.length];
  const cc = index % 3 !== 2;
  return {
    id: `File:Demo ${subject} ${index}.jpg`,
    source: "wikimedia-commons",
    sourceLabel: "Wikimedia Commons",
    title: `${subject} (example ${index + 1})`,
    description: `An invented example picture of ${subject.toLowerCase()}, shown in the local preview only.`,
    creator: `Example Creator ${index + 1}`,
    licence: cc ? { kind: "cc-by", name: "CC BY 4.0", url: "https://creativecommons.org/licenses/by/4.0" } : { kind: "public-domain", name: "Public domain", url: null },
    sourceUrl: "https://commons.wikimedia.org/wiki/Commons:Welcome",
    imageUrl: picture(subject, HUES[index % HUES.length]),
    width: 1280,
    height: 960,
  };
}

export function createDemoStockImageClient(delayMilliseconds = 300): StockImageClient {
  return {
    async search({ cursor, exclude }) {
      await new Promise((resolve) => setTimeout(resolve, delayMilliseconds));
      const start = /^\d+$/.test(cursor) ? Number.parseInt(cursor, 10) : 0;
      const candidates: StockCandidate[] = [];
      let at = start;
      while (candidates.length < 4 && at < 40) {
        const candidate = demoCandidate(at);
        at += 1;
        if (!exclude.includes(candidate.id)) candidates.push(candidate);
      }
      return { candidates, nextCursor: at < 40 ? String(at) : null };
    },
    async fetchPicked(candidate) {
      await new Promise((resolve) => setTimeout(resolve, delayMilliseconds));
      const svg = decodeURIComponent(candidate.imageUrl.replace(/^data:image\/svg\+xml;charset=utf-8,/, ""));
      return { candidate, file: new File([svg], `${candidate.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.svg`, { type: "image/svg+xml" }), pickedBy: "preview-editor" };
    },
  };
}
