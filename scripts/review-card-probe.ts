// Renders the Needs me detail for one review request from JSON on argv and prints its text. Used by features_backend/review-card.feature.
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReviewRequest } from "../lib/review-requests";

(globalThis as { React?: typeof React }).React = React;

const input = JSON.parse(process.argv[2] ?? "{}") as { request: ReviewRequest; deletedStories?: string[]; storyTitles?: Record<string, string> };
const ratings = {
  get: () => ({ pending: null, askReason: false, feedback: { phase: "idle" as const } }),
  choose: () => undefined, setReason: () => undefined, setNote: () => undefined, commitNote: () => undefined, cancelReason: () => undefined,
};
async function main() {
  const { buildNeedsMeItems } = await import("../lib/needs-me-items");
  const { NeedsMeDetail } = await import("../components/needs-me-detail");
  const [item] = buildNeedsMeItems({
    references: [], decisions: undefined, previews: new Map(), captures: undefined, visitRated: new Set(), requests: [input.request], drafts: {}, missingDrafts: new Set(),
    draftsState: "ready", stay: new Set([input.request.id]), bySource: new Map(), storyTitles: input.storyTitles ?? {}, storyExcerpts: {},
    deletedStories: new Set(input.deletedStories ?? []), emails: [], emailsDecided: new Map(),
  });
  const html = renderToStaticMarkup(createElement(NeedsMeDetail, {
    item, ratings, extras: { why: "", notThisKind: false }, onExtras: () => undefined, disabledReason: null, attachments: [], demo: false, predictionLoading: false,
  }));
  process.stdout.write(html.replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/\s+/g, " "));
}

void main();
