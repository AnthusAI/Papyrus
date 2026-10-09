Feature: A Papyrus relevance run is recorded for the Cyclotron marketing site
  The recording follows the editorial-run fixture's schema 2 with source
  "papyrus-live". It shows real decisions before real reviews, measured model
  usage and cost at list prices, and editors' explanations only where they
  agreed to be quoted.

  Background:
    Given a publication with a relevance cyclotron
    And two pending references and one accepted reference
    And the decide-relevance sweep has run with apply
    And an editor rejected the first pending reference as "out_of_scope" saying "Vendor marketing." and allowed quoting
    And an editor accepted the second pending reference saying "On our beat."
    And the decide-relevance sweep has run with apply

  Scenario: The recording follows the editorial-run fixture shape
    When the relevance recording is exported
    Then the recording is schema version 2 from source "papyrus-live"
    And it has one cycle per decision in the order they were made
    And each reviewed cycle shows the decision before the review, the editor's label and its reason code
    And the first window counts 2 decisions and 2 reviewed
    And the first window and the total carry decision-model usage and cost at the Jev list price

  Scenario: Explanations appear only with the editor's consent
    When the relevance recording is exported
    Then the explanation "Vendor marketing." is in the recording
    And the text "On our beat." is not in the recording
    And the text "editor-7" is not in the recording

  Scenario: Explanations can be switched off entirely
    When the relevance recording is exported without explanations
    Then the text "Vendor marketing." is not in the recording

  Scenario: A run that called the optimizer needs the optimizer's list price
    When a recording with optimizer calls is exported without an optimizer price
    Then the export asks for the optimizer's list price and its source

  Scenario: The export command reads the private bucket and calls no model
    When the export command writes the recording from the private bucket
    Then the recording file has 2 cycles
