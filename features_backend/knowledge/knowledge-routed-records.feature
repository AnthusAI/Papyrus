Feature: Routed monitor records count in the Knowledge Map as data on any site
  The shared relevance router delivers stories from monitors, today Hacker News and later
  RSS or arXiv, to many sites. Each delivery is a pending Reference in the site's own
  knowledge corpus, with a provenance relation that names the monitor that routed it. Those
  stories are signal before anyone has judged them, so a site can ask the weekly knowledge
  run to count them as data, just as it can for Hugging Face Hub models: in entities and in
  the weekly trends, and never as pages or as members of topic-model clusters.

  A routed story has a title and no structured fields, so the run links it to the map
  by reading its text: the title, and a summary or excerpt when the monitor stored one. The
  text is matched, without regard to case and on whole words, against the names and aliases
  of the entities that are already accepted on the site's map. It never creates an entity,
  never links a generated or rejected one, and calls no model. A name of one short word,
  like "Go", never matches by accident.

  The site opts in with "routed" in the knowledge run setting monitorSources. A site that
  does not opt in gets exactly the snapshot it got before.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"
    And the router delivered the story "cloning" titled "Show HN: Voice cloning in 3 seconds, from Acme" on 2026-10-14
    And the router delivered the story "sourdough" titled "Why my sourdough failed" on 2026-10-15
    And the router delivered the story "novel" titled "Quantum Gardening is trending" on 2026-10-16
    And the router delivered the story "scam" titled "Acme scams" on 2026-10-15 and a person rejected it
    And a Reference "imported" with no monitor behind it, titled "Acme, added by hand", is in the corpus
    And the map has the accepted entities of the site's items

  Scenario: Any monitor's delivered Reference becomes a record, and a Reference no monitor delivered does not
    Given the router delivered the story "paper" titled "Voice cloning with transformers" on 2026-10-13 through the monitor "arxiv"
    When the corpus is exported for "shipped" with the monitor source "routed" as of 2026-10-19
    Then the monitor records are "cloning" from "hn", "novel" from "hn", "paper" from "arxiv" and "sourdough" from "hn"
    And the corpus holds the item documents "alpha" and "beta" and no record document

  Scenario: A story links to the accepted entities its title names, with the monitor as provenance
    Given the corpus was exported with the routed records
    When the run is imported with the monitor records
    Then the story "cloning" is linked to "maker--acme" and to nothing else
    And those links are confirmed, marked as monitor links, with the provenance "routed from the hn monitor"
    And the story "sourdough" is linked to nothing

  Scenario: A name the map does not have is never made into an entity
    Given the corpus was exported with the routed records
    When the run is imported with the monitor records
    Then there is no entity "concept--quantum-gardening"
    And the story "novel" is linked to nothing

  Scenario: Importing the same routed records again changes nothing
    Given the corpus was exported with the routed records
    And the run was imported with the monitor records
    When the run is imported with the monitor records
    Then nothing was written

  Scenario: An entity that reaches the map links the stories that name it
    Given the corpus was exported with the routed records
    And the run was imported with the monitor records and an import ledger
    And an editor accepted the entity "Quantum Gardening" on the map
    When the routed records are exported again and the run is imported again with the import ledger
    Then the story "novel" is linked to "concept--quantum-gardening" and to nothing else

  Scenario: Routed records count in entities by their date, as data with no page of their own
    Given the corpus was exported with the routed records
    And the run was imported with the monitor records
    When the snapshot is built as of 2026-10-19 with the monitor records
    Then the entity "maker--acme" counts 1 record and 3 items in all
    And the entity "maker--acme" lists the story "cloning" with the address "https://example.org/cloning" apart from its items
    And the story "cloning" is cited as "routed from the hn monitor"

  Scenario: An entity only routed stories and Hub models mention has no wiki page
    Given the Hugging Face monitor delivered "gizmo/voice" released on 2026-10-14
    And the router delivered the story "gizmo" titled "Gizmo announces a new release" on 2026-10-16
    And the corpus was exported with the monitor sources "huggingface" and "routed"
    And the run was imported with the monitor records
    And the corpus was exported with the monitor sources "huggingface" and "routed"
    And the run was imported with the monitor records
    When the wiki sync plans its pages with the monitor records
    Then the story "gizmo" is linked to "maker--gizmo" and to nothing else
    And there is no wiki page for "maker--gizmo"

  Scenario: Cited Trends can cite a routed story as a release from its monitor
    Given the corpus was exported with the routed records
    And the run was imported with the monitor records
    And the snapshot was built as of 2026-10-19 with the monitor records
    When the trend signals are built for "maker--acme"
    Then the signal for "maker--acme" has the story "Show HN: Voice cloning in 3 seconds, from Acme" from "routed from the hn monitor" dated 2026-10-14
    And no page of that story is fetched

  Scenario: A site that did not opt in gets exactly the snapshot it had
    Given the Hugging Face monitor delivered "org/base" released on 2026-10-06
    And the snapshot of the Hub records alone was taken as of 2026-10-19
    When the corpus is exported for "shipped" with the monitor source "huggingface" as of 2026-10-19
    And the snapshot of the Hub records alone is taken as of 2026-10-19 again
    Then the two snapshots are byte for byte the same
    And the monitor records file holds 1 records

  Scenario: Routed stories are not offered for promotion as if they were Hub models
    Given the corpus was exported with the routed records
    When the weekly suggestion runs for the 2 records the Hub shows the most interest in
    Then no review request was raised for a routed story
