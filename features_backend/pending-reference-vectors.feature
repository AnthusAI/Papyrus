@backend @pending-reference-vectors
Feature: Pending References are in the vector index as context, so the Related section can work for them, and no reader ever sees one
  A Reference that a monitor or a person has just added waits for an editor in the Needs me feed, and the Related section on its page suggests other References
  by comparing its summary vector with those of the accepted ones. Until now the site's index held only accepted References, so a pending one had no vector and
  nothing could be suggested for it. The owner decided that pending References may be used as context only. So the index now holds the summary vector of every
  current Reference that is accepted or pending, each vector marked with the Reference's curation status; a pending Reference has no passage vectors until it is
  accepted. Whatever the index is asked for on behalf of readers, a pending Reference is never an answer: the suggestions, the context packs and the knowledge
  search all ask for accepted References only, and a search drops a pending one even if it came back. The index follows the Reference through its life: when a
  pending Reference is accepted its vectors are marked accepted without a new embedding and its passages are written, when an accepted one goes back to
  pending its passages are removed, and when a Reference is rejected, archived or superseded its vectors are deleted (or, where the router's role may not delete,
  marked with that status so every query still skips them). The router's daily pass picks up the accepted and the pending References since its last pass and
  suggests links for both. The index, the embeddings and the backends are fakes in these scenarios.

  Scenario: A pending Reference is indexed as context with its summary vector only
    Given a site index with the accepted Reference "alpha" and the pending Reference "beta"
    When the index is synced
    Then "beta" has a summary vector marked pending and no passage vectors
    And "alpha" has a summary vector marked accepted and passage vectors

  Scenario: Rejected, archived and superseded References are not indexed
    Given a site index with the rejected Reference "gamma", the archived Reference "delta" and a superseded version of "epsilon"
    When the index is synced
    Then the index holds no vector for them

  Scenario: Accepting a pending Reference marks its vectors accepted without a new embedding and adds its passages
    Given a site index with the pending Reference "beta"
    When "beta" is accepted and the index is synced
    Then the vectors of "beta" are marked accepted
    And "beta" has passage vectors
    And its summary vector was not embedded again

  Scenario: Sending an accepted Reference back to pending removes its passages
    Given a site index with the accepted Reference "alpha"
    When "alpha" goes back to pending and the index is synced
    Then "alpha" has a summary vector marked pending and no passage vectors

  Scenario: Rejecting a Reference removes it from the index
    Given a site index with the accepted Reference "alpha" and the pending Reference "beta"
    When both are rejected and the index is synced
    Then the index holds no vector for them

  Scenario: Where the router may not delete, a rejected Reference's vectors are marked with its status
    Given a site index with the accepted Reference "alpha" in which deleting vectors is not allowed
    When "alpha" is rejected and the index is synced
    Then the vectors of "alpha" are marked rejected
    And the sync records that deleting was denied

  Scenario: The router's pass indexes and suggests for the pending References too
    Given a publication whose Reference "one" was accepted at "2026-10-30T10:00:00Z" and "two" is pending since "2026-10-31T10:00:00Z"
    When the router's vector pass runs
    Then both References are indexed and suggested for, the pending one first
    And the pass reports 1 newly accepted and 1 newly pending Reference
    And the pass saves a place for the pending and the accepted group

  Scenario: Suggestions for a pending Reference come from accepted References only
    Given a pending Reference "reference-p" with a stored vector, another pending Reference close to it and an accepted one a little further
    When suggestions are made for "reference-p"
    Then the accepted Reference is suggested
    And the pending Reference is not

  Scenario: A search never returns a pending Reference
    Given the knowledge search asks the index for a topic
    When the index also returns a pending Reference
    Then the search results leave it out
    And the search filter asks for accepted References whatever curation status the request names
