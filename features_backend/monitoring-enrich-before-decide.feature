@backend @monitoring
Feature: A collected item is curated before it is decided and before an editor rates it
  The lab should decide on the text an editor will see, and an editor should rate exactly what the lab
  decided on, with no second revision in between. So the router curates each collected item once, at
  discovery: it reads the whole source, records signals about how complete the capture looks, writes a
  summary and, for a research paper, extracts the paper's structure. The lab decision is then posted on
  that enriched text. When the item is delivered, the same curation is copied onto each delivered Reference.
  Curation never stops a decision: whatever exists when it has been attempted is what is used.

  Background:
    Given a live router with one collected story and an enrichment that can read the article

  Scenario: A collected item is enriched before it is posted
    When the enriching router runs
    Then the story was read exactly once for all three publications
    And the story's enrichment is "ready"
    And every decision request was sent after the enrichment finished

  Scenario: The decision request carries the summary and the captured text
    When the enriching router runs
    Then each decision request carries the summary and the full captured text inside its text
    And the request text is the title, the address, the summary and the captured text

  Scenario: Delivery copies the curation onto each delivered Reference
    When the enriching router runs
    Then every delivered Reference has a "ready" curation card holding the summary the lab was given
    And every delivered Reference holds the same captured text the lab was given
    And the post-delivery curation has nothing left to do

  Scenario: A capture failure still proceeds to the decision, with a typed status
    Given the article source refuses the request as "blocked"
    When the enriching router runs
    Then the story's enrichment ended "capture_failed" because the capture failed as "blocked"
    And each decision request carries only the title and the address

  Scenario: Nothing is posted before enrichment has been attempted
    Given the article source times out
    When the enriching router runs
    Then no decision request was sent
    And the story's enrichment is waiting for a retry
    When the enriching router runs after the retry delay and the article source still times out until the last attempt
    Then each decision request carries only the title and the address
    And the story's enrichment ended "capture_failed" because the capture failed as "timeout"

  Scenario: A very long source is sent whole
    Given the article is far longer than any size the router once cut to
    When the enriching router runs
    Then every decision request carries the whole body once, inside its text
    And the story's discovery records no cut
