/** The Story Preview pane opens with the headline, then the deck, then the blurb. Synthetic data in the shape that was reported: an em dash and a question mark in the title, an apostrophe in the deck. */
import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import * as React from "react";
(globalThis as { React?: unknown }).React = React;
import { StoryPreviewHeading } from "../components/story-preview-heading";
import { storyHeadings } from "../lib/front-matter-fields";

const TITLE = "A Home Surveillance Drone with Cloud AI — What Could Go Wrong?";
const DECK = "Ring's Drone Cam is sold as security. To do its job it has to see every room and send the video to the cloud, which is a privacy risk of its own.";
const PLAIN = `title: ${TITLE}\ndeck: ${DECK}\n`;
const FOLDED = `title: ${TITLE}\ndeck: Ring's Drone Cam is sold as security. To do its job it has to see every room\n  and send the video to the cloud, which is a privacy risk of its own.\nblurb: Two or three lines.\n`;
const QUOTED = `title: "A Home Surveillance Drone with Cloud AI \\u2014 What Could Go Wrong?"\ndeck: >-\n  ${DECK}\n`;
const html = (yaml: string) => renderToStaticMarkup(React.createElement(StoryPreviewHeading, { frontMatterYaml: yaml, slug: "a-home-surveillance-drone" }));

test("the title is the headline and the deck is only the deck, for plain, folded and quoted front matter", () => {
  for (const yaml of [PLAIN, FOLDED, QUOTED]) {
    const headings = storyHeadings(yaml, "slug");
    assert.equal(headings.title, TITLE);
    assert.equal(headings.deck, DECK);
  }
});

test("the Preview pane draws the headline before the deck", () => {
  const markup = html(PLAIN);
  assert.match(markup, /<h2[^>]*data-newsroom-article-headline[^>]*>A Home Surveillance Drone with Cloud AI — What Could Go Wrong\?<\/h2>/);
  assert.ok(markup.indexOf("data-newsroom-article-headline") < markup.indexOf("data-newsroom-article-deck"));
  assert.ok(!markup.includes("data-newsroom-article-blurb"), "no blurb element when the front matter has none");
});

test("a Story with no title still has a headline: its address", () => {
  assert.equal(storyHeadings("deck: Only a deck.\n", "only-a-deck").title, "only-a-deck");
  assert.match(renderToStaticMarkup(React.createElement(StoryPreviewHeading, { frontMatterYaml: "deck: Only a deck.\n", slug: "only-a-deck" })), />only-a-deck<\/h2>/);
});
