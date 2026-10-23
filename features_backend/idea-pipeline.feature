Feature: The idea pipeline turns a site's recent references into private story ideas
  A publication's monitors and curators keep adding references. The idea pipeline reads what arrived in a window and groups it
  in a digest, then asks one model to propose story ideas that combine several of those references. The digest is deterministic
  and uses no model. The model sees the site's mission and policy, its sections, its recent and in-flight stories and any
  earlier drafts, and every idea must cite at least two references that are really in the digest. Ideas that resemble a story or
  draft the site already has are dropped and reported. Each kept idea is stored as a private draft proposed by AI; nothing is
  published, and the run records what it read, what it dropped and what the model call cost. A person reviews the ideas later.

  Background:
    Given a site with five accepted references that arrived in the last week
    And the site has a mission, the sections "Analysis" and "News", and a published story "Prompt injection breaks AI agents"

  Scenario: The digest groups the window's references by section and label
    Given two of the references carry the "include" relevance label
    When the operator builds a digest for the last 7 days
    Then the digest lists 5 references
    And the digest has a group of 2 references labelled "include" and a group of 3 labelled "unlabelled"
    And every reference in the digest names its title, source, status and why it was included

  Scenario: Pending references are left out unless the operator asks for them
    Given one more reference is pending review
    When the operator builds a digest for the last 7 days
    Then the digest lists 5 references
    When the operator builds a digest for the last 7 days including pending references
    Then the digest lists 6 references
    And the pending reference is marked as not yet reviewed

  Scenario: The same references always give the same digest
    When the operator builds a digest for the last 7 days
    And the operator builds a digest for the last 7 days again
    Then both digests have the same id and the same content

  Scenario: An idea that combines two references is kept as a private draft
    When the model proposes the idea "Agents and keys" citing the first two references
    And the operator synthesizes ideas from the digest
    Then 1 idea is created
    And the idea is a draft story proposed by AI that cites those two references
    And the idea is private and nothing is written to a public data directory

  Scenario: An idea resting on one reference is dropped
    When the model proposes the idea "One source only" citing only the first reference
    And the operator synthesizes ideas from the digest
    Then 0 ideas are created
    And the run reports the idea as dropped for having fewer than two citations

  Scenario: An idea citing a reference that is not in the digest is dropped
    When the model proposes the idea "Made up" citing the first reference and a reference that does not exist
    And the operator synthesizes ideas from the digest
    Then 0 ideas are created
    And the run reports the idea as dropped for citing an unknown reference

  Scenario: An idea that repeats a published story is dropped and recorded
    When the model proposes the idea "Prompt injection still breaks AI agents" that restates the published story
    And the operator synthesizes ideas from the digest
    Then 0 ideas are created
    And the run reports 1 near-duplicate of the published story "Prompt injection breaks AI agents"

  Scenario: An idea a reviewer declined is not proposed again
    Given a reviewer declined the idea "Rotating cloud keys safely"
    When the model proposes the idea "Safely rotating cloud keys" citing the first two references
    And the operator synthesizes ideas from the digest with the reviewer feedback
    Then 0 ideas are created
    And the model was shown the reviewer feedback

  Scenario: A site with the proposals model files each idea as a draft Proposal
    When the model proposes the ideas "Cloud key rotation" and "Model checkpoint signing" citing different references
    And the operator synthesizes ideas from the digest into the site's proposals
    Then 2 draft story proposals are filed
    And no request to publish proposals is made

  Scenario: The run records what it read and what the model call cost
    When the model proposes the idea "Agents and keys" citing the first two references
    And the model reports 100000 input tokens and 10000 output tokens
    And the operator synthesizes ideas from the digest
    Then the run records 5 references, 1 story and the model name
    And the run records the cost of the model call in dollars from the recorded price

  Scenario: A run too expensive for its cap makes no model call
    When the operator synthesizes ideas with a cost cap of a millionth of a dollar
    Then the run is refused before any model call

  Scenario: A run only records that human review is pending
    When the model proposes the idea "Agents and keys" citing the first two references
    And the operator synthesizes ideas from the digest
    Then the run records a pending review of 1 idea that was not requested from anyone
