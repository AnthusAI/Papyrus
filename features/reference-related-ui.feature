@brand-agnostic @related-fixtures
Feature: Editors see and manage what a Reference is related to
  Under a Reference's review card is a Related section with a link icon. Concepts show as chips with a hash icon and the hashtag.
  References show as cards with the title, the host, the way they are related in words, and both dates: "published 2026-10-27 ·
  added 2026-10-28", or "published unknown" when the source has no date of its own. A suggestion carries a sparkles icon and the word
  "Suggested", the close match as text such as "close match 0.81", and "likely" or "possible" when the site can say. Each suggestion
  has the one shared Accept and Reject control with an optional reason box. An editor adds a link by typing in one box: a hash for
  a concept, or a link or words of a title for a Reference, and the matches appear as full-width buttons under the box. A Suggest
  more button asks for more suggestions, and where the site has no knowledge index it says "Suggestions need the knowledge index"
  while confirmed links and typed hashtags still work. On a concept page, "Linked by editors" lists the References people linked,
  each with both dates, with the same box to link another. Every mark has a word beside it, nothing is a drop-down, and there are no
  borders. These scenarios use synthetic data in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: Concepts and References show with words beside every mark
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor opens the Related section
    Then the confirmed concept is a chip with a hash icon and its hashtag
    And a suggested link says "Suggested" with a sparkles icon, its close match as text, and likely or possible when known
    And a Reference card shows the title, the host and the relation in words

  Scenario: Both dates show on every Reference card
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor opens the Related section
    Then every Reference card says when it was published and when it was added
    And a Reference with no publication date says "published unknown"

  Scenario: The feed card and the Reference detail show both dates
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor looks at the feed card and the Reference detail header
    Then each says "published <date> · added <date>" as plain text with no border
    And a month-precision date reads "published Oct 2026" and a year-precision date reads "published 2026"
    And a Reference with no publication date says "published unknown" and never shows the added date as published

  Scenario: Accepting a suggestion makes it a confirmed link
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor accepts the suggested concept
    Then the decision is saved with the accept choice
    And the concept becomes a plain chip without the word "Suggested"

  Scenario: Rejecting a suggestion offers an optional reason
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor writes a reason and rejects the suggested Reference
    Then the reason box is offered beside the Accept and Reject buttons
    And the decision is saved with the reject choice and the reason
    And the suggestion leaves the list

  Scenario: Adding a concept by hashtag
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor types a hash and the start of a concept name and presses the match
    Then the matches are full-width buttons under the box
    And a human link to that concept is written and the box clears
    And the concept shows as a chip

  Scenario: Adding a Reference by link or by title
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor pastes a link and then types words of a title
    Then each match shows its title, host and both dates as a full-width button
    And pressing one writes a human link to that Reference

  Scenario: A site without a knowledge index still works
    Given a site with no knowledge index and a Reference with one confirmed concept
    When the editor presses Suggest more and then adds a concept by its exact hashtag
    Then the section says "Suggestions need the knowledge index"
    And the confirmed concept is still listed and the typed hashtag is linked

  Scenario: The concept page lists the References editors linked
    Given a concept page with two References linked by editors
    When the editor opens the concept page
    Then "Linked by editors" lists both References with both dates
    And pasting a link in the box there links another Reference to the concept

  Scenario: Flat tones, rounded rectangles, no drop-downs
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor looks at the Related section at 375 and 1440 pixels
    Then there are no borders or outlines and no drop-downs
    And nothing scrolls sideways
