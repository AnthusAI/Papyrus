// Renders one Notification Center review card from JSON on argv and prints its text. Used by features_backend/review-card.feature.
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReviewRequest } from "../lib/review-requests";

(globalThis as { React?: typeof React }).React = React;

const input = JSON.parse(process.argv[2] ?? "{}") as { request: ReviewRequest; deletedStories?: string[]; storyTitles?: Record<string, string> };
async function main() {
  const { NotificationCenterView } = await import("../components/notification-center");
  const html = renderToStaticMarkup(createElement(NotificationCenterView, {
    loadState: "ready", requests: [input.request], stay: new Set([input.request.id]),
    storyTitles: input.storyTitles ?? {}, deletedStories: new Set(input.deletedStories ?? []),
  }));
  process.stdout.write(html.replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/\s+/g, " "));
}

void main();
