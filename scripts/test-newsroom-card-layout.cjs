#!/usr/bin/env node

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

require.extensions[".ts"] = function loadTs(module, filename) {
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: filename,
  });
  module._compile(output.outputText, filename);
};

const { resolveNewsroomCardTemplate } = require("../lib/newsroom-card-layout.ts");

const severeHeadline = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 0,
  title: "Institutional Alignment For Long Horizon Agentic Evaluation And Governance In Public Knowledge Infrastructure",
  bodyLength: 80,
  isUrgent: false,
});
assert.deepEqual(severeHeadline, { role: "wideFeature", span: "3x2" });

const longNonLeadHeadline = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 4,
  title: "A Comparative Study Of Governance Failures In Multimodal Model Deployment And Public Evidence Review",
  bodyLength: 90,
  isUrgent: false,
});
assert.deepEqual(longNonLeadHeadline, { role: "wide", span: "3x1" });

const denseSubtitle = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 2,
  title: "Compact Source Note",
  bodyLength: 260,
  isUrgent: false,
});
assert.deepEqual(denseSubtitle, { role: "tall", span: "1x2" });

const urgentShortHeadline = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 1,
  title: "Short Pending Reference",
  bodyLength: 40,
  isUrgent: true,
});
assert.deepEqual(urgentShortHeadline, { role: "priority", span: "2x1" });

const lowQualityLongHeadline = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 0,
  title: "Institutional Alignment For Long Horizon Agentic Evaluation And Governance In Public Knowledge Infrastructure",
  bodyLength: 360,
  isUrgent: true,
  qualityRating: 2,
});
assert.deepEqual(lowQualityLongHeadline, { role: "standard", span: "1x1" });

const adequateQualityLongHeadline = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 0,
  title: "Institutional Alignment For Long Horizon Agentic Evaluation And Governance In Public Knowledge Infrastructure",
  bodyLength: 360,
  isUrgent: true,
  qualityRating: 3,
});
assert.deepEqual(adequateQualityLongHeadline, { role: "wideFeature", span: "3x2" });

const stableBeforeSelection = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 4,
  title: "A Comparative Study Of Governance Failures In Multimodal Model Deployment And Public Evidence Review",
  bodyLength: 90,
  isUrgent: false,
});
const stableAfterSelection = resolveNewsroomCardTemplate({
  mode: "desk",
  sectionKey: "references",
  index: 4,
  title: "A Comparative Study Of Governance Failures In Multimodal Model Deployment And Public Evidence Review",
  bodyLength: 90,
  isUrgent: false,
});
assert.deepEqual(stableAfterSelection, stableBeforeSelection);

const css = fs.readFileSync(path.join(__dirname, "../app/globals.css"), "utf8");
const workspace = fs.readFileSync(path.join(__dirname, "../components/topic-steering-workspace.tsx"), "utf8");
assert.match(css, /\.newsroom-card--span-3x1/);
assert.match(css, /\.newsroom-card--span-3x2/);
assert.match(css, /@media \(max-width: 971px\)[\s\S]*\.newsroom-card--span-3x1,[\s\S]*grid-column: span 2;/);
assert.match(css, /@media \(max-width: 1157px\)[\s\S]*\[data-news-desk-section="references"\] \.newsroom-card-grid[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);/);
assert.match(css, /@media \(max-width: 1157px\)[\s\S]*\[data-news-desk-section="references"\] \.newsroom-card--span-3x1,[\s\S]*grid-column: span 2;/);
assert.match(css, /@media \(max-width: 1157px\)[\s\S]*\.newsroom-list-detail-shell \.news-desk-main-column,[\s\S]*\.newsroom-list-detail-shell \.news-desk-rail-column[\s\S]*grid-column: 1 \/ -1;/);
assert.match(css, /@media \(max-width: 430px\)[\s\S]*\.newsroom-card--span-3x1,[\s\S]*grid-column: span 1;/);
assert.doesNotMatch(css, /\.newsroom-card--span-[^{]+\.newsroom-card__title\s*\{[\s\S]*?font-size:/);
assert.match(css, /\.newsroom-card\[data-newsroom-card-quality="low"\] \.newsroom-card__title\s*\{[\s\S]*?-webkit-line-clamp: 4;/);
assert.match(workspace, /"data-newsroom-card-quality": isLowReferenceQualityRating\(qualityRating\) \? "low" : undefined/);

console.log("newsroom-card-layout\tok");
