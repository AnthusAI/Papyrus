Feature: Every accepted concept has a concept card vector
  The knowledge vector index holds one concept_card vector for every accepted
  concept, built from the concept's display name, kind, aliases and description,
  so a concept is findable by meaning even before it has an AI profile. The
  card carries the concept's node key, node kind, lineage and hashtag. Sync is
  idempotent: a card whose text has not changed is not embedded again, and only
  the cards that changed are sent to the embedding model.

  Scenario: Sync writes one card for each accepted concept
    Given a vector index with no vectors
    And an accepted concept "Voice Cloning" of kind "task" and a rejected concept "Spam Topic" of kind "task"
    When the vector index is synced
    Then exactly 1 concept card is written
    And the written card has the node key "task--voice-cloning" and the hashtag "#voice-cloning"
    And the written card carries the vector kind "concept_card" and the node kind "task"

  Scenario: A second sync skips unchanged cards
    Given a vector index with no vectors
    And an accepted concept "Voice Cloning" of kind "task" and a rejected concept "Spam Topic" of kind "task"
    And the vector index was synced once
    When the vector index is synced
    Then no concept card is written
    And 1 concept card is reported as unchanged

  Scenario: Only a changed card is embedded again
    Given a vector index with no vectors
    And an accepted concept "Voice Cloning" of kind "task" and a rejected concept "Spam Topic" of kind "task"
    And the vector index was synced once
    And the description of "Voice Cloning" changes
    When the vector index is synced
    Then exactly 1 concept card is written

  Scenario: An accepted Reference with no extracted text is indexed from its curation summary and skipped when unchanged
    Given a vector index with no vectors
    And an accepted Reference delivered by a monitor, with a curation summary and no extracted text
    When the Reference summary vectors are synced
    Then exactly 1 Reference summary vector is written, with the summary source "curation" and no passage vectors
    When the Reference summary vectors are synced
    Then no Reference summary vector is written
