import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

// The newsroom shell's own chrome follows the feed's rule: no outlines or rules, controls are tone fills in rounded rectangles.
// The markup below mirrors NewsroomOpsShell's class names; the CSS is the real stylesheet.
const css = readFileSync("components/newsroom-organizer.css", "utf8");
const shell = readFileSync("components/newsroom-ops-shell.tsx", "utf8");
const workspace = readFileSync("components/topic-steering-workspace.tsx", "utf8");
assert.doesNotMatch(shell + workspace, /NewsroomOpsSearchButton/, "the bar has one search field and no second search button");
for (const source of [workspace, readFileSync("components/newsroom-access-gate.tsx", "utf8")]) {
  assert.match(source, /"organizer-header-settings"\)\} href="\/settings">Settings/, "the header Settings link can step aside on a phone");
}

const html = `<html><head><meta name="viewport" content="width=device-width"><style>:root{--org-paper:#eef1f6;--org-ink:#111;--org-line:#999;--org-sidebar:#e4e8ef;--org-muted:#555;--org-accent:#36c}${css}</style></head><body>
<div class="newsroom-organizer" data-sidebar-collapsed="false">
  <aside class="organizer-sidebar"><div class="organizer-sidebar-head"><a class="organizer-brand">Anthus</a><button class="organizer-toggle">|</button></div>
    <nav class="organizer-destinations"><section><h3>Editorial work</h3><a aria-current="page"><strong>Articles</strong><small>Follow stories</small></a></section></nav>
    <button class="organizer-account organizer-account-sidebar"><span><strong>editor</strong><small>Account</small></span></button></aside>
  <div class="organizer-workspace"><header class="organizer-topbar"><a class="organizer-masthead">A</a><h1 data-newsroom-ops-title>Newsroom home</h1>
    <form class="organizer-search"><input type="search" placeholder="Search"></form>
    <div class="organizer-header-actions"><a class="organizer-header-settings">Settings</a></div>
    <button class="organizer-account organizer-account-header"><span><strong>editor</strong></span></button></header>
    <main class="organizer-main">page</main></div>
  <nav class="organizer-bottom-nav"><ul><li><a aria-current="page">Articles</a></li></ul></nav>
</div></body></html>`;

assert.match(shell, /className="organizer-public-site" href=\{backHref\}/, "the phone More menu links to the public site");
assert.match(readFileSync("components/needs-me-feed.tsx", "utf8"), /Each answer is saved as a label for the Cyclotron\./);
assert.doesNotMatch(readFileSync("components/needs-me-feed.tsx", "utf8"), /teaches the Cyclotron|reorders what comes next/, "no sentence claims a vote retrains or reorders");

void (async () => {
  const browser = await chromium.launch();
  try {
    for (const width of [375, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 800 } });
      await page.setContent(html);
      const styles = await page.evaluate(() => [".organizer-sidebar", ".organizer-toggle", ".organizer-search", ".organizer-account-header", ".organizer-account-sidebar", ".organizer-bottom-nav"].map((selector) => {
        const element = document.querySelector(selector)!;
        const style = getComputedStyle(element);
        return { selector, shown: style.display !== "none", borders: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth], radius: style.borderTopLeftRadius };
      }));
      for (const { selector, shown, borders, radius } of styles) {
        if (!shown) continue;
        assert.deepEqual(borders, ["0px", "0px", "0px", "0px"], `${selector} has no border at ${width}px`);
        if (selector !== ".organizer-sidebar" && selector !== ".organizer-bottom-nav") assert.equal(radius, "8px", `${selector} is a rounded rectangle at ${width}px`);
      }
      const bar = await page.evaluate(() => {
        const [title, settings] = ["[data-newsroom-ops-title]", ".organizer-header-settings"].map((selector) => document.querySelector(selector)!.getBoundingClientRect().width > 2);
        const header = document.querySelector(".organizer-topbar")!;
        return { title, settings, titleText: document.querySelector("[data-newsroom-ops-title]")!.textContent, overflow: header.scrollWidth > header.clientWidth + 1 };
      });
      assert.equal(bar.titleText, "Newsroom home", "the page title stays for screen readers");
      assert.equal(bar.title, width > 900, width > 900 ? "the bar names the page on a wide screen" : "on a phone the page's own heading names it, so the bar drops the cut-off title");
      assert.equal(bar.settings, width > 900, "on a phone Settings lives in the account menu");
      assert.equal(bar.overflow, false, `nothing in the bar is cut off at ${width}px`);
      if (width <= 900) for (const count of [3, 4, 5]) {
        // The bottom tabs centre for any count (Chat is offered on some sites): equal space left and right of the row.
        const offsets = await page.evaluate((tabs) => {
          document.querySelector(".organizer-bottom-nav ul")!.innerHTML = Array.from({ length: tabs }, (_, index) => `<li><a>Tab ${index}</a></li>`).join("");
          const items = Array.from(document.querySelectorAll(".organizer-bottom-nav li")).map((item) => item.getBoundingClientRect());
          return { left: items[0].left, right: window.innerWidth - items[items.length - 1].right };
        }, count);
        assert.ok(Math.abs(offsets.left - offsets.right) < 1, `${count} bottom tabs are centred at ${width}px (${offsets.left} left, ${offsets.right} right)`);
      }
      await page.close();
    }
  } finally {
    await browser.close();
  }
  console.log("newsroom chrome: ok");
})();
