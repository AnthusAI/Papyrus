Feature: Monitor records count in the Knowledge Map as data
  A site can run a monitor, for example the Hugging Face Hub model list, whose models are
  delivered as pending References for a person to judge. Those models are signal even
  while nobody has judged them: how many open models were released this week, by whom,
  under which licence, built on which base. But they are not the site's own stories, so
  the weekly knowledge run counts them as data and never turns them into pages.

  A site opts in with the knowledge run setting monitorSources. A delivered model then
  becomes a monitor record: a corpus document dated by the model's own release date,
  the structured entities its Hub fields name, and a "built on" relation to its base
  model when both are on the map. A rejected model is left out. The weekly snapshot
  counts the records next to the site's own items, lists them apart from the items,
  and the Cited Trends step can cite them as releases from the Hub. A person promotes
  a notable record to a normal item draft with approval; nothing here publishes.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"
    And the Hugging Face monitor delivered "org/base" released on 2026-10-06
    And the Hugging Face monitor delivered "org/tuned" released on 2026-10-14 and built on "org/base" as finetune and on "elsewhere/gone" as adapter
    And the Hugging Face monitor delivered "org/lone" released on 2026-10-15 under the licence "mit" for the task "image-classification"
    And the Hugging Face monitor delivered "org/refused" released on 2026-10-15 and a person rejected it

  Scenario: A site that did not opt in exports its items only
    When the corpus is exported without monitor sources
    Then the corpus holds the item documents "alpha" and "beta" and no record document

  Scenario: The corpus gets a document per delivered model, dated by its release, except the rejected one
    When the corpus is exported for "shipped" with the monitor source "huggingface" as of 2026-10-19
    Then the corpus holds the record documents "org/base", "org/lone" and "org/tuned"
    And the record document "org/tuned" is dated 2026-10-14T08:00:00Z and marked kind monitor-record
    And the record document "org/tuned" says it is built on "org/base" and holds no model card text
    And the monitor records file holds 3 records

  Scenario: An unsupported monitor source is refused
    When the corpus is exported for "shipped" with the monitor source "rss" as of 2026-10-19
    Then the export is refused with "Unsupported monitor source"

  Scenario: Entities come from the Hub's structured fields, without the extractor
    Given the corpus was exported with the monitor records
    When the run is imported with the monitor records
    Then the entity "model--org-tuned" exists, accepted by the "Hugging Face Hub import"
    And the entities "maker--org", "licence--apache-2-0", "licence--mit", "task--text-to-speech" and "task--image-classification" exist
    And there is no entity "model--org-refused"

  Scenario: A base model becomes a built-on relation with its subtype, its evidence and its provenance
    Given the corpus was exported with the monitor records
    When the run is imported with the monitor records
    Then "org/tuned" is built on "org/base" as finetune, confirmed, with the evidence "https://huggingface.co/org/tuned" and the provenance "from the Hugging Face Hub"
    And there is no relation for the base model "elsewhere/gone" because it is not on the map

  Scenario: Importing the same records again changes nothing
    Given the corpus was exported with the monitor records
    And the run was imported with the monitor records
    When the run is imported with the monitor records
    Then nothing was written

  Scenario: Records count in the weekly snapshot by release week and have no page
    Given the corpus was exported with the monitor records
    And the run was imported with the monitor records
    When the snapshot is built as of 2026-10-19 with the monitor records
    Then the entity "maker--org" counts 3 records, 3 items in all, and links to no page
    And the entity "maker--org" lists the record "org/tuned" with the address "https://huggingface.co/org/tuned" apart from its items
    And the entity "model--org-lone" is not on the map
    And the entity "model--org-tuned" shows the built-on neighbour "model--org-base" as finetune

  Scenario: An entity only records mention has no wiki page
    Given the corpus was exported with the monitor records
    And the run was imported with the monitor records
    When the wiki sync plans its pages with the monitor records
    Then there is no wiki page for "maker--org"

  Scenario: Cited Trends can cite a record as a release from the Hub
    Given the corpus was exported with the monitor records
    And the run was imported with the monitor records
    And the snapshot was built as of 2026-10-19 with the monitor records
    When the trend signals are built from the published snapshot
    Then the signal for "maker--org" has the release "org/tuned" from the Hugging Face Hub dated 2026-10-14
    And that release carries its own summary and no page of it is fetched
