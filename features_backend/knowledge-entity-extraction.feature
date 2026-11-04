Feature: Jev decides what kind of concept each name in the texts is
  The weekly knowledge run has to find the entities in a publication's texts. It used to
  hand the texts to a local model that tagged spans, ran for minutes on the CPU and needed
  gigabytes of weights in the image. The run now reads the texts itself, with no model, to
  find the names that could be concepts, and asks Jev one question per distinct name: which
  of the publication's kinds is this, or is it not a concept at all, as the name is used in a
  few passages from different documents? Asking once per name, not once per mention, keeps the
  bill small, and the answers are remembered, so a second run over the same texts asks nothing.

  A name the wiki already holds is not asked about: its mentions point at the accepted
  entity. Jev's confidence is kept on every entity it proposes and nothing is cut off here,
  because the import's candidate filter and the AI review decide what stays. Jev does not
  propose relations, so the file has none.

  Background:
    Given a corpus of two documents that both read "Tern3 beat GPT-4 today. Maple Lab built Tern3."
    And the publication's vocabulary has the kinds "model" and "organization"
    And the wiki already holds the model "GPT-4" as "model--gpt-4"
    And Jev answers "Tern3" is a model with confidence 0.35, and "Maple Lab" is an organization with confidence 0.9

  Scenario: Every mention of a concept is an entity of the kind Jev chose
    When the entities are extracted
    Then the item "doc-1" has the proposed model "Tern3" twice, with confidence 0.35
    And the item "doc-1" has the proposed organization "Maple Lab" once, with confidence 0.9
    And the file has no relations

  Scenario: A name the wiki holds resolves to its entity without asking Jev
    When the entities are extracted
    Then the item "doc-1" has the resolved model "GPT-4" with the entity key "model--gpt-4"
    And Jev was not asked about "GPT-4"

  Scenario: A low confidence is kept, not cut off
    Given Jev answers "Tern3" is a model with confidence 0.02
    When the entities are extracted
    Then the item "doc-1" has the proposed model "Tern3" twice, with confidence 0.02

  Scenario: A name is asked about once, however often it appears
    When the entities are extracted
    Then Jev was asked about "Tern3" once and about "Maple Lab" once

  Scenario: A second run over the same texts asks nothing and costs nothing
    Given the entities were extracted
    When the entities are extracted again
    Then Jev was not asked anything
    And the run reports no paid calls
    And the file is the same as the first time

  Scenario: A word is never found inside a longer word
    Given a corpus of two documents that both read "The Organization of Experts met. Organization of Experts spoke."
    When the entities are extracted
    Then no entity of the file starts or ends in the middle of a word

  Scenario: A name never runs across a line break
    Given a corpus of two documents that both read "ChatGPT" and "Medical" in separate paragraphs
    When the entities are extracted
    Then no entity of the file spans a line break

  Scenario: A name Jev does not answer fails the run without losing what was paid for
    Given Jev does not answer for "Maple Lab"
    When the entities are extracted
    Then the command fails saying Jev gave no answer for 1 name
    And no entities file is written
    And Jev's answer for "Tern3" is kept, so running again asks only about "Maple Lab"
