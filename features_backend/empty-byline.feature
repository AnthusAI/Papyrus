@backend @byline
Feature: A site can say an item has no byline
  A site's `byline` hook returns the complete byline text of an item. Returning `None`, or having no hook, shows the item's authors ("By Ryan Porter"). Returning an
  empty string says the item has NO byline, for example a post, which nobody writes: neither the page nor the Markdown twin falls back to the authors. Before this
  rule the empty string was treated like no hook, and the Markdown twin of every post said "By <author>" even though the page said nothing.

  Scenario: With no hook the authors are shown
    When the byline of an item is drawn with no hook
    Then the Markdown twin and the page show "Ryan Porter"

  Scenario: A hook byline replaces the authors
    When the byline of an item is drawn with the hook text "By various bots and Ryan Porter"
    Then the Markdown twin and the page show "By various bots and Ryan Porter"

  Scenario: An empty hook byline means no byline at all
    When the byline of an item is drawn with an empty hook text
    Then neither the Markdown twin nor the page shows "Ryan Porter"
    And the Markdown twin still says it was published on "2026-11-09"
