@brand-agnostic @needs-me-link-fixtures
Feature: Link suggestions wait in "What needs me", ranked most likely first, so editors can review them in bulk
  The vector index suggests links: between two References, or from a Reference to a concept. Each is an open suggestion that an editor
  may Accept or Reject, and every answer keeps its optional explanation with the link. Deciding one at a time from the
  Related section of each Reference meant nobody reviewed them, so they are now also items in the Needs me feed. Each suggestion is a
  card of the type "Link suggestion" and the Links pill counts them. They are ranked by the close match the index recorded, 0.91 before
  0.84, and a suggestion with no close match comes last. The index records no probability, so a suggestion has no prediction and is never
  decided automatically; it always waits for a person. Only the first page is read when the editor arrives, and a "Load more link
  suggestions" button reads the next, so thousands of suggestions are never loaded at once. A card opens the same detail pane as any
  Needs me item. Its body shows the two References side by side on a wide pane, one above the other on a phone, each with its title,
  its host and both dates as "published 2026-10-27 · added 2026-10-28", or a Reference and a concept chip with a hash icon. Under them is the one shared
  Accept and Reject control with the optional "Why?" box: buttons and a text box, no drop-downs, no borders, Lucide icons. Deciding calls
  the same decide-link action the Related section uses, so the decision and the reason are recorded the same way. A decided
  suggestion stays where it is showing its answer, like every other item, and Next goes on to the following one. These scenarios use
  synthetic data in an isolated browser at 390 and 1440 pixels and never touch production.

  Scenario: Suggestions are cards ranked by close match, counted by the Links pill
    Given an isolated Needs me feed with four suggested links
    When the editor opens the Links pill at 390 and 1440 pixels
    Then each suggestion is a card of the type "Link suggestion" with Accept and Reject, ordered by close match from 0.91 down
    And the header says how many link suggestions are waiting and the other pills leave them out
    And nothing scrolls sideways, there are no drop-downs and every icon is a Lucide icon

  Scenario: Only a page of suggestions is read at a time
    Given an isolated Needs me feed with four suggested links read two at a time
    When the editor presses "Load more link suggestions"
    Then only the first page was read on arrival and the next page is read from where the first ended
    And the new suggestions are placed in the feed at once and the button goes when the queue ends

  Scenario: The detail shows both ends with both dates beside the shared Accept and Reject
    Given an isolated Needs me feed with four suggested links
    When the editor opens the first suggestion on a wide screen and on a phone
    Then the two References sit side by side on the wide screen and one above the other on the phone, each with its host and "published <date> · added <date>"
    And the shared Accept and Reject buttons and the optional Why box are there, with no drop-down

  Scenario: Accepting saves the decision and the reason through the decide-link action
    Given an isolated Needs me feed with four suggested links
    When the editor writes a reason, accepts the first suggestion and presses Next
    Then the decide-link action is called with the relation, the accept decision and the reason
    And the decided suggestion says so and the next suggestion opens

  Scenario: Rejecting without a reason saves no note, and a refusal leaves the suggestion open
    Given an isolated Needs me feed whose first save is refused
    When the editor rejects the first suggestion, sees the refusal and rejects it again
    Then nothing was recorded by the refused save and the second save records a reject with no note

  Scenario: The page's own related-links store is what the feed reads and decides through
    Given an isolated Needs me feed that reads links through the page's related-links store
    When the editor rejects the first suggestion with a reason on the page's own related-links store
    Then the decision goes through the related-links store's own decide, exactly as the Related section calls it

  Scenario: A suggestion between a Reference and a concept shows the concept as a chip
    Given an isolated Needs me feed with four suggested links
    When the editor opens the suggestion that names a concept
    Then the concept is a chip with a hash icon and its hashtag beside the Reference with both of its dates
