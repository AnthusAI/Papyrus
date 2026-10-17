const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");
const { Given, When, Then } = require("@cucumber/cucumber");

function registerTypeScriptRequire() {
  if (require.extensions[".ts"]) return;
  require.extensions[".ts"] = (module, filename) => {
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
}

function loadBlogRhythm() {
  registerTypeScriptRequire();
  return require("../../lib/blog-rhythm.ts");
}

function loadBlogFeatureSolver() {
  registerTypeScriptRequire();
  return require("../../lib/blog-feature-solver.ts");
}

const LANDSCAPE_IMAGE_ASSET = { layout: { aspectRatio: 1.5 } };

Given("the default blog vertical rhythm", function () {
  this.blogRhythm = loadBlogRhythm().createDefaultBlogVerticalRhythm();
});

Then("the rhythm row height should be {int} pixels", function (expected) {
  assert.equal(this.blogRhythm.rowHeight, expected);
});

Then("a height of {int} pixels should reserve {int} pixels", function (height, expected) {
  assert.equal(loadBlogRhythm().reserveRhythmRows(height, this.blogRhythm), expected);
});

Then("a height of {int} pixels should snap to the nearest row at {int} pixels", function (height, expected) {
  assert.equal(loadBlogRhythm().snapToNearestRhythm(height, this.blogRhythm), expected);
});

When("I derive the blog text style for the font {string}", function (fontFamily) {
  this.blogTextStyle = loadBlogRhythm().createDefaultBlogTextStyle(fontFamily);
});

Then("the blog font size should be {int} pixels", function (expected) {
  assert.equal(this.blogTextStyle.fontSize, expected);
});

Then("the blog line height should be {int} pixels", function (expected) {
  assert.equal(this.blogTextStyle.lineHeight, expected);
});

Then("the blog line paint height should equal the line height", function () {
  assert.equal(this.blogTextStyle.linePaintHeight, this.blogTextStyle.lineHeight);
});

When(
  "I solve a featured float for a {int} pixel container in a {int} pixel viewport at item {int}",
  function (containerWidth, viewportWidth, itemIndex) {
    this.featuredFloat = loadBlogFeatureSolver().solveFeaturedFloatGeometry({
      containerWidth,
      viewportWidth,
      itemIndex,
      imageAsset: LANDSCAPE_IMAGE_ASSET,
    });
  },
);

Then("the featured image width should be {int} pixels", function (expected) {
  assert.equal(this.featuredFloat.imageWidth, expected);
});

Then("the featured gap should be {int} pixels", function (expected) {
  assert.equal(this.featuredFloat.gap, expected);
});

Then("the featured image height, media height and gap should be whole rhythm rows", function () {
  const rowHeight = this.blogRhythm.rowHeight;
  assert.equal(this.featuredFloat.imageHeight % rowHeight, 0);
  assert.equal(this.featuredFloat.mediaHeight % rowHeight, 0);
  assert.equal(this.featuredFloat.gap % rowHeight, 0);
});

Then("the featured layout mode at {int} pixels with an image should be {string}", function (viewportWidth, expected) {
  assert.equal(loadBlogFeatureSolver().getFeaturedLayoutMode(viewportWidth, true), expected);
});

Then("the featured layout mode at {int} pixels without an image should be {string}", function (viewportWidth, expected) {
  assert.equal(loadBlogFeatureSolver().getFeaturedLayoutMode(viewportWidth, false), expected);
});
