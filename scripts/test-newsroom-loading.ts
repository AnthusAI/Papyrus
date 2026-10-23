import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NewsroomOverviewSkeleton } from "../components/newsroom-overview-skeleton";

const html = renderToStaticMarkup(createElement(NewsroomOverviewSkeleton));
assert.match(html, /role="status"/);
assert.match(html, /aria-label="Loading newsroom overview"/);
assert.match(html, /newsroom-overview-feed-frame/);
assert.match(html, /aria-label="Needs attention"/);
assert.doesNotMatch(html, /aria-label="Destinations"|Go to/);
assert.doesNotMatch(html, /Nothing needs attention|No pending references|animate-|motion-safe:/);
console.log("newsroom loading skeleton: ok");
