Feature: Export a publication's editor labels for Cyclotron priming
  An editor's decisions are the best examples a new Cyclotron can start from. The export reads the publication's
  backend and writes one JSON line per item in the shape the lab imports. It only reads, it labels nothing an editor
  did not judge, and it never writes an address.

  Scenario: An editor's curation decision on a Reference becomes a relevance label
    Given a Reference "ref-a" an editor accepted with the reason "On topic"
    And a Reference "ref-r" an editor rejected with the reason "Not about marks"
    When the priming export runs for the publication
    Then the export has 2 rows
    And the row "ref-ref-a" is labeled "distinctive-relevance" "include" by an editor, not made by a model
    And the row "ref-ref-r" is labeled "distinctive-relevance" "exclude" by an editor, not made by a model

  Scenario: A decision the monitoring worker made is marked as made by a model
    Given a Reference "ref-m" the monitoring worker accepted
    When the priming export runs for the publication
    Then the row "ref-ref-m" is labeled "distinctive-relevance" "include" by an automation, made by a model

  Scenario: Pending References are left out unless unlabeled rows are asked for
    Given a Reference "ref-p" that is still pending
    When the priming export runs for the publication
    Then the export has 0 rows
    When the priming export runs for the publication including unlabeled rows
    Then the export has 1 rows
    And the row "ref-ref-p" has no labels

  Scenario: An editor publishing a draft the TTAB automation wrote is an accepted draft
    Given a TTAB draft for proceeding "99185689" that an editor moved to "published"
    When the priming export runs for the publication
    Then the row "ttab-99185689-2026-10-06" is labeled "distinctive-draft-accept" "include" by an editor, not made by a model
    And the row "ttab-99185689-2026-10-06" has no "distinctive-relevance" label

  Scenario: An editor holding a draft is a declined draft
    Given a TTAB draft for proceeding "99185689" that an editor moved to "held"
    When the priming export runs for the publication
    Then the row "ttab-99185689-2026-10-06" is labeled "distinctive-draft-accept" "exclude" by an editor, not made by a model

  Scenario: A draft still in the pipeline has no label
    Given a TTAB draft for proceeding "99185689" that an editor moved to "typesetting"
    When the priming export runs for the publication
    Then the export has 0 rows
    When the priming export runs for the publication including unlabeled rows
    Then the row "ttab-99185689-2026-10-06" has no labels

  Scenario: No address reaches the export
    Given a Reference "ref-e" an editor accepted with the reason "Ask editor.person@example.test about it"
    When the priming export runs for the publication
    Then the export text contains no "@"

  Scenario: The text is the title, the address, the summary and the full body
    Given a Reference "ref-t" an editor accepted with a summary "A summary." and the body "Full body."
    When the priming export runs for the publication
    Then the row "ref-ref-t" has the text "Title of ref-t\nhttps://example.test/ref-t\n\nA summary.\n\nFull body."
