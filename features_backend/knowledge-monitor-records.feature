Feature: Monitor records count in the Knowledge Map as data
  A site can run a monitor, for example the Hugging Face Hub model list, whose models are
  delivered as pending References for a person to judge. Those models are signal even
  while nobody has judged them: how many open models were released this week, by whom,
  under which licence, built on which base. But they are not the site's own stories, so
  the weekly knowledge run counts them as data and never turns them into pages.

  A site opts in with the knowledge run setting monitorSources. A delivered model then
  becomes a monitor record: a row of the run's monitor records file dated by the model's own
  release date (data only: it is not a corpus document, so the topic model never clusters it),
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

  Scenario: Records are data only and stay out of the topic model
    When the corpus is exported for "shipped" with the monitor source "huggingface" as of 2026-10-19
    Then the corpus holds the item documents "alpha" and "beta" and no record document
    And the monitor records file holds 3 records

  Scenario: A site can still ask for a document per delivered model in the topic model
    When the corpus is exported with the records in the topic model for "shipped" from the monitor source "huggingface" as of 2026-10-19
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

  Scenario: A person promotes a record to a draft item
    When a person promotes "org/tuned" to the section "models"
    Then a draft item "item-models-org-tuned" exists in the section "models"
    And the draft carries the source link "https://huggingface.co/org/tuned", the structured facts and the entities of the record
    And nothing is published and the Reference is still pending

  Scenario: Promoting twice never overwrites the editor's text
    Given a person promoted "org/tuned" to the section "models"
    And the editor rewrote the draft
    When a person promotes "org/tuned" to the section "models"
    Then the draft still holds the editor's text

  Scenario: The week's run asks for ONE soft review of the records most worth a look
    Given the corpus was exported with the monitor records
    When the weekly suggestion runs for the 2 records the Hub shows the most interest in
    Then one soft review request lists "org/base" and "org/lone" with their reference ids, the model id deciding between records that tie
    And running the suggestion again raises no second request

  Scenario: A site that cannot take review requests is not failed by the suggestion
    Given the corpus was exported with the monitor records
    When the weekly suggestion runs on a site without review requests
    Then the suggestion says it was not raised and the run goes on
