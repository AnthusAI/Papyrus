Feature: A site can build its knowledge map from its accepted References alone
  A Papyrus site normally gets its knowledge map from its published items, and from its
  References when they have extracted text under the site's corpus. A site that lost its
  extracted files, or whose sources arrive through monitors, still has the most trustworthy
  material it could ask for: the References an editor accepted, each with the text that
  curation captured when it was accepted.

  A site opts in with an explicit option on the corpus export, and in the cloud run with
  the setting that carries it. In that mode every accepted Reference of the site's corpus
  is a document, whichever monitor delivered it, and its text is the curation text, or the
  editor's corrected text when an editor corrected it. A Reference nobody accepted is never
  a document, and neither is one an editor rejected.

  The export never stays quiet about a gap. A Reference with no text is listed by its id
  with the reason. A site with no accepted Reference that has a text gets an error and
  nothing is written, and nothing already exported is removed: an empty answer is not
  evidence that the sources are gone. A site that does not set the option gets exactly the
  corpus it got before.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"
    And the corpus accepted the Reference "paper" with the curation text "Acme released Tern 3 this week."
    And the corpus accepted the Reference "delivered" which the monitor "hn" brought, with the curation text "A monitor found Tern 3."
    And the corpus accepted the Reference "notext" but captured no curation text
    And the corpus holds the pending Reference "waiting" with the curation text "Nobody accepted this."
    And the corpus holds the rejected Reference "refused" with the curation text "An editor rejected this."

  Scenario: Accepted References are the documents, whichever monitor delivered them
    When the corpus is exported from the accepted References
    Then the corpus holds the accepted Reference documents "delivered" and "paper"
    And the document of "paper" has the title "Paper paper" and the body "Acme released Tern 3 this week."
    And the accepted Reference "delivered" is a document and not a monitor record

  Scenario: A Reference with no text is reported by id and reason
    When the corpus is exported from the accepted References
    Then the export report lists the Reference "notext" with a reason saying it has no curation text

  Scenario: A site with nothing to read fails loudly and loses nothing
    Given the corpus was exported from the accepted References
    When an editor sends every Reference back to pending
    And the corpus is exported from the accepted References
    Then the export fails saying it found no accepted Reference with a text
    And the corpus still holds the accepted Reference documents "delivered" and "paper"

  Scenario: A concept extracted from an accepted Reference is mentioned by that Reference
    Given the corpus was exported from the accepted References
    When the entity "Tern 3" is extracted from the accepted Reference "delivered" and the run is imported
    Then the entity "Tern 3" is mentioned by the Reference "delivered" with a Reference mention link

  Scenario: Without the option nothing changes
    When the corpus is exported without the Reference documents
    Then the corpus holds no Reference document
