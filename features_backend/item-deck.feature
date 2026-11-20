Feature: A Story's deck column is always the dek of its front matter
  A Story's dek lives in its front matter, under the key `dek`. The Item's `deck` column is a copy that feeds the feeds, the newsroom context
  pack, announcements, reference curation, the boards and the published row. There is one rule for the copy, used by every way of saving a
  version: the first non-blank of `dek`, `deck`, `standfirst`, `description`. `dek` is the canonical spelling, so a Story whose front matter says
  `dek` can no longer keep serving an older deck. The copy is never edited on its own.

  Scenario: A version saved with a dek stores that dek as its deck
    Given a deck Story saved with the dek "First dek."
    When a new deck version is saved with the dek "Second dek."
    Then the newest deck version's deck is "Second dek."

  Scenario: When a front matter holds several spellings, dek wins
    When a deck Story is saved whose front matter has the dek "Chosen." and the deck "Stale."
    Then the newest deck version's deck is "Chosen."

  Scenario: The published row serves the same dek
    Given a deck Story saved with the dek "Served dek."
    When the deck Story is published
    Then the published deck row is "Served dek."

  Scenario: A Story with no dek of any spelling has no deck
    When a deck Story is saved whose front matter has no dek
    Then the newest deck version has no deck
