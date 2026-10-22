Feature: A model is its own kind of entity, related to its family only when the source says so
  The publication's closed vocabulary has a "model" kind for a specific named model
  (CosyVoice2, CosyVoice 3) next to the "model family" kind for the line of models
  above it. The two stay separate kinds with separate labels on entity chips and wiki
  pages. A model is tied to its family with the "member of" relation, and a model whose
  family nothing established has no such relation: the relation is never guessed.

  Scenario: Model and model family are separate kinds with their own labels
    Given an accepted model "Tern 3" and an accepted model family "Tern" mentioned in one item
    When the knowledge snapshot is built
    Then the snapshot lists the kinds "model" and "model_family" with the labels "Model" and "Model Family"
    And the wiki page text for "Tern 3" says it is listed as a "model"
    And the wiki page text for "Tern" says it is listed as a "model family"

  Scenario: A confirmed member of relation ties a model to its family in both directions
    Given an accepted model "Tern 3" and an accepted model family "Tern" mentioned in one item
    And a confirmed "member_of" relation from the model "Tern 3" to the family "Tern"
    When the knowledge snapshot is built
    Then the neighbours of "Tern 3" include "Tern" as "member_of"
    And the neighbours of "Tern" include "Tern 3" as "member_of"

  Scenario: A model whose family nobody established stays unrelated
    Given an accepted model "Tern 3" and an accepted model family "Tern" mentioned in one item
    And an accepted model "Lone 1" mentioned in another item
    And a confirmed "member_of" relation from the model "Tern 3" to the family "Tern"
    When the knowledge snapshot is built
    Then "Lone 1" has no "member_of" neighbour

  Scenario: Member of is a registered ontology relation between two concepts
    When the seeded relation type "member_of" is read
    Then it is an ontology relation labelled "member of" that runs from a semantic node to a semantic node
    And it is not transitive or symmetric
