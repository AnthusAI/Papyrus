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
  borders. The same Related section is on the References page: opening an accepted Reference there shows its concepts, links and
  suggestions between the review card's content and the messages. When Suggest more has nothing to suggest it says so in plain
  words ("Suggestions appear once this Reference has a summary.") and never shows an internal reason; a reason it does not know gets
  "No suggestions could be made for this Reference yet.", and any other failure says "Suggestions could not be made right now. Try
  again in a moment." These scenarios use synthetic data in an isolated browser at 375 and 1440 pixels and never touch production.
  The words an editor writes when they accept or make a link are meaning, not decoration. Every accepted or hand-made link, a Reference card
  or a concept chip, shows its explanation in a plain rounded block with a quote icon and the word "Explanation", and says who wrote it and
  when: "Written by an editor on 2026-10-31" (the link keeps an account id, not a name). An editor adds or changes the words in place with
  the same text box as everywhere else, and Save, Cancel and Edit say what they do; saving goes through the same decision that accepted the
  link, so the link stays accepted. A reason typed when accepting a suggestion becomes its explanation. A viewer without editor access reads
  the words and has no way to change them. A suggestion has no explanation, and the reason given when rejecting one is never shown as one.
  The idea writer reads the same words (features_backend/link-explanations-in-packs.feature).

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

  Scenario: The References page detail shows the Related section with its suggestions
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor opens that Reference on the References page at 390 and 1440 pixels in the light and dark themes
    Then the detail shows the Related section with its suggestions and the Accept and Reject buttons
    And the Related section comes before the messages and Reference cards link to their own detail

  Scenario: A viewer sees the Related section but cannot change links
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When a viewer without editor access opens that Reference on the References page
    Then the section says "Editor access is required to change links."
    And Suggest more and the add box are disabled

  Scenario: A Reference opened with no links gets its suggestions once, by itself
    Given a Reference with no links that nobody has asked suggestions for
    When the editor opens the Related section of that Reference
    Then the suggestions are asked for once without a press and show as soon as the answer comes

  Scenario: Typing a hashtag no concept has offers one action that makes the concept and tags the Reference
    Given a Reference with no links that nobody has asked suggestions for
    When the editor types a hashtag that no concept has, taps the create action twice and then does the same with Enter
    Then one concept and one confirmed link are made, the existing name offers itself instead of a second concept, and the action shows a Lucide icon in light and dark at 375 and 1440 pixels

  Scenario: The concept an editor made takes a description on its own page
    Given a concept page for a concept an editor made
    When the editor adds a description in place
    Then the words are saved without a dialog and the button then says Edit description

  Scenario: Suggest more explains an empty result in plain words
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor presses Suggest more and the site reports that the Reference has no summary vector, or a reason it does not know
    Then the note says "Suggestions appear once this Reference has a summary." for the first
    And the note says "No suggestions could be made for this Reference yet." for the unknown reason
    And the note never contains internal wording

  Scenario: An accepted link shows the editor's explanation and who wrote it
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor reads the explanations on the confirmed links
    Then each confirmed link shows its words in a block with a quote icon, and says "Written by an editor" with the date
    And the suggestions show no explanation

  Scenario: An editor changes an explanation in place
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the editor edits, cancels, clears and adds explanations on the links, and accepts a suggestion with a reason
    Then saving records an accept decision carrying the new words, so the link stays accepted
    And cancelling saves nothing, and clearing the words offers Add explanation again
    And the reason given when accepting a suggestion becomes its explanation

  Scenario: The concept page shows and edits the explanation of each link
    Given a concept page with two References linked by editors
    When the editor reads and adds an explanation under "Linked by editors"
    Then the explanation that exists is shown and the link without one offers Add explanation
    And adding words records an accept decision with them

  Scenario: A viewer reads explanations and cannot change them
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When a viewer without editor access reads the explanations
    Then the explanations are readable and no Edit, Add explanation or text box is offered

  Scenario: An accepted link's explanation is shown on a phone and a desktop in both themes
    Given a Reference with a confirmed concept, a confirmed Reference link, a suggested concept and a suggested Reference
    When the explanation is shown and being edited at 390 and 1440 pixels in the light and dark themes
    Then nothing scrolls sideways and the page raises no errors
