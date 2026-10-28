import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// tsx compiles JSX with the classic runtime; the app uses the automatic one, so give the component a React in scope.
Object.assign(globalThis, { React });

void (async () => {
  const { NotificationSkeleton } = await import("../components/notification-cards");

  // The access gate shows the feed's own skeleton while the session is checked, so what loads replaces it in place.
  const gate = readFileSync("components/newsroom-access-gate.tsx", "utf8");
  assert.match(gate, /<NotificationSkeleton /);
  assert.doesNotMatch(gate, /NewsroomOverviewSkeleton|data-newsroom-page-skeleton/);

  for (const bare of [false, true]) {
    const html = renderToStaticMarkup(React.createElement(NotificationSkeleton, { bare, count: 4 }));
    assert.match(html, /role="status"/);
    assert.match(html, /data-feed-surface/);
    // Flat fills and rounded rectangles, like the loaded feed: no outlines.
    assert.doesNotMatch(html, /(^|\s|")border(\s|"|-)/);
    assert.doesNotMatch(html, /Nothing needs attention|No pending references/);
  }
  console.log("newsroom loading skeleton: ok");
})();
