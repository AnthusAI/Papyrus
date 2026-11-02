Feature: A site's References with extracted text are documents of its knowledge run
  A Papyrus site keeps its sources as References in a knowledge corpus: the PDFs and pages
  an editor or an importer added. When the extractor has turned a Reference into text, that
  text is what a reader would cite, so a site can ask the weekly knowledge run to read it:
  the topic model, the entity extractor and the wiki then work on the sources themselves
  and not only on the few articles the site has published. The site opts in with
  referenceDocuments in the knowledge run setting. A site that does not opt in gets exactly
  the corpus it got before.

  This is a different source from monitor records. A Reference a monitor delivered is data
  for counts and is never a document, however much text it has, because thousands of
  delivered titles once drowned the editorial clusters. A Reference that was added as a
  source is a document.

  Each document is one file named after its Reference, carrying the Reference's own
  address and source date so the wiki can cite it. A Reference with no extracted text, such
  as a citation-graph stub that is only a title, is not a document. An entity found in a
  document is linked from the Reference, and once the entity is accepted the Reference is
  one of the sources the Knowledge Map and the wiki show for it.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"
    And the corpus holds the Reference "paper" with the extracted text "Acme released Tern 3 this week." dated 2026-09-10
    And the corpus holds the Reference "survey" with the extracted text "A survey of voice models." with no source date
    And the corpus holds the Reference "stub" with no extracted text
    And the corpus holds the Reference "refused" with the extracted text "Rejected words." which a person rejected
    And the router delivered the story "cloning" titled "Show HN: Voice cloning" on 2026-10-14

  Scenario: A Reference with extracted text becomes a document, and nothing else does
    When the corpus is exported with the Reference documents
    Then the corpus holds the item files "alpha" and "beta"
    And the corpus holds the Reference documents "paper" and "survey"
    And there is no document for the Reference "stub", the Reference "refused" or the story "cloning"

  Scenario: A document carries the address and the source date the wiki cites
    When the corpus is exported with the Reference documents
    Then the document of "paper" cites "https://example.org/paper.pdf" and is dated 2026-09-10
    And the document of "paper" has the title "Paper paper" and the body "Acme released Tern 3 this week."
    And the document of "survey" has no date

  Scenario: A text that did not change is not downloaded again
    Given the corpus was exported with the Reference documents
    When the corpus is exported with the Reference documents again
    Then no extracted text was downloaded
    When the extracted text of "paper" changes to "Acme released Tern 4."
    And the corpus is exported with the Reference documents again
    Then only the extracted text of "paper" was downloaded
    And the document of "paper" has the title "Paper paper" and the body "Acme released Tern 4."

  Scenario: A Reference that stops being a source stops being a document
    Given the corpus was exported with the Reference documents
    When a person rejects the Reference "paper"
    And the corpus is exported with the Reference documents again
    Then the corpus holds the Reference documents "survey" only

  Scenario: Without the option the corpus holds the site's items only
    When the corpus is exported without the Reference documents
    Then the corpus holds the item files "alpha" and "beta"
    And the corpus holds no Reference document

  Scenario: Monitor records stay data when the Reference documents are on
    When the corpus is exported with the Reference documents and the monitor source "routed"
    Then the monitor records are "cloning" from "hn"
    And there is no document for the Reference "stub", the Reference "refused" or the story "cloning"

  Scenario: An entity found in a document is linked from the Reference and shown with it once accepted
    Given the corpus was exported with the Reference documents
    And the map has the accepted entities of the site's items
    When the entity "Tern 3" is extracted from the document of "paper" and the run is imported
    Then the entity "Tern 3" is mentioned by the Reference "paper" and by no item
    And that link is an unconfirmed extractor link marked as a Reference mention
    When an editor accepts the entity "Tern 3"
    And the snapshot is taken with the Reference documents
    Then the entity file for "Tern 3" lists the Reference "paper" as a source with its address
    And the entity "Tern 3" has a wiki page

  Scenario: Without the Reference documents the snapshot does not count the Reference
    Given the corpus was exported with the Reference documents
    And the map has the accepted entities of the site's items
    And the entity "Tern 3" was extracted from the document of "paper", imported and accepted
    When the snapshot is taken without the Reference documents
    Then there is no entity file for "Tern 3"
