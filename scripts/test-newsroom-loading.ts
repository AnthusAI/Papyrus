import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NewsroomOverviewSkeleton } from "../components/newsroom-overview-skeleton";

const html = renderToStaticMarkup(createElement(NewsroomOverviewSkeleton));
assert.match(html, /role="status"/);
assert.match(html, /aria-label="Loading newsroom overview"/);
assert.match(html, /newsroom-overview-feed-frame/);
assert.match(html, /aria-label="Destinations"/);
assert.match(html, /aria-label="Needs attention"/);
assert.equal((html.match(/h-32 rounded-xl border bg-card p-4/g) ?? []).length, 8, "destination placeholders match the overview cards");
assert.doesNotMatch(html, /Nothing needs attention|No pending references|animate-|motion-safe:/);
console.log("newsroom loading skeleton: ok");
