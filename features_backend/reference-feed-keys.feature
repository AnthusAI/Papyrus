@backend @reference-feed-keys
Feature: The References page pages through two indexes whose keys every writer keeps right
  The newsroom References page used to download every Reference, every attachment and every decision, and rank them in the browser. It
  now asks for one page at a time from one of two indexes on the Reference itself. Both are partitioned by a feed state: a Reference that
  nobody has voted on is in the unrated feed of its corpus, one that is accepted or rejected is in the rated feed, and one that is archived
  or is no longer the current version is in neither. "Best bets" is sorted by the Cyclotron's original chance that the editor accepts
  (P of accept), highest first, then newest first. "Newest" is sorted by when the Reference arrived. The prediction is a value written on
  the Reference once, when the Cyclotron first decides it. It is the confidence of the include label, or one minus the confidence of the
  exclude label. A Reference nobody has predicted sorts as one half, after every predicted Accept and before every predicted Reject. A vote
  moves a Reference between the feeds and never touches its prediction. Nothing here touches production: the backend is in memory.

  Scenario: Recording a prediction writes the original accept confidence onto the Reference
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    When the Cyclotron decides "include" with 91% confidence and the publication's positive label is "include"
    Then the Reference records an accept probability of 0.91
    And the Reference records when the Cyclotron decided it
    And its Best bets key is "0.910000#2026-10-28T12:00:00.000Z#" followed by its id
    And it is still in the unrated feed

  Scenario: A predicted Reject is recorded as the chance of an Accept, not the confidence of the label
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    When the Cyclotron decides "exclude" with 80% confidence and the publication's positive label is "include"
    Then the Reference records an accept probability of 0.2

  Scenario: A later decision does not replace the original prediction
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    And the Cyclotron decided "include" with 91% confidence
    When the Cyclotron decides "exclude" with 99% confidence and the publication's positive label is "include"
    Then the Reference still records an accept probability of 0.91
    And nothing more was written to the Reference

  Scenario: An unpredicted Reference sorts between a predicted Accept and a predicted Reject
    Given pending References that arrived together with predicted accept probabilities 0.9, none, 0.2 and 0.5
    When their Best bets keys are read highest first
    Then the order is 0.9, then the two without a prediction or at one half, then 0.2

  Scenario: Newest sorts by arrival whatever the prediction
    Given pending References that arrived at "2026-10-26T00:00:00Z", "2026-10-28T00:00:00Z" and "2026-10-27T00:00:00Z"
    When their Newest keys are read latest first
    Then the order is "2026-10-28T00:00:00.000Z", "2026-10-27T00:00:00.000Z", "2026-10-26T00:00:00.000Z"

  Scenario: A vote moves the Reference from the unrated to the rated feed
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    And the Cyclotron decided "include" with 91% confidence
    When the Cyclotron accepts it automatically
    Then it is in the rated feed of its corpus
    And the Reference still records an accept probability of 0.91
    And its Best bets key is unchanged

  Scenario: A rejection moves the Reference to the rated feed as well
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    When the Cyclotron rejects it automatically
    Then it is in the rated feed of its corpus

  Scenario: An archived Reference is in no feed
    Given an archived Reference
    Then it is in no feed

  Scenario: A superseded version is in no feed
    Given a pending Reference that is not the current version
    Then it is in no feed

  Scenario: The backfill sets the keys and changes nothing else
    Given a corpus with these References and no feed keys
      | name    | status   | decision                    |
      | fresh   | pending  | include with 90% confidence |
      | doubted | pending  | exclude with 70% confidence |
      | unseen  | pending  | none                        |
      | voted   | accepted | include with 60% confidence |
      | dropped | archived | include with 95% confidence |
    When the feed key backfill runs for that corpus
    Then each backfill write names only the Reference id and feed key fields
    And the "fresh" Reference is unrated with an accept probability of 0.9
    And the "doubted" Reference is unrated with an accept probability of 0.3
    And the "unseen" Reference is unrated with no accept probability and sorts as one half
    And the "voted" Reference is rated with an accept probability of 0.6
    And the "dropped" Reference is in no feed
    And the backfill reports 5 scanned, 4 predictions recorded and 1 without a prediction

  Scenario: Running the backfill again writes nothing
    Given a corpus with these References and no feed keys
      | name  | status  | decision                    |
      | fresh | pending | include with 90% confidence |
    When the feed key backfill runs for that corpus
    And the feed key backfill runs for that corpus again
    Then the second run wrote nothing

  Scenario: A dry run reports what it would change and writes nothing
    Given a corpus with these References and no feed keys
      | name  | status  | decision                    |
      | fresh | pending | include with 90% confidence |
      | other | pending | none                        |
    When the feed key backfill runs for that corpus as a dry run
    Then the dry run wrote nothing to the References
    And the backfill reports 2 scanned and 2 changed

  Scenario: The backfill keeps a prediction a Reference already has
    Given a corpus with these References and no feed keys
      | name  | status  | decision                    |
      | fresh | pending | include with 90% confidence |
    And the "fresh" Reference already records an accept probability of 0.4
    When the feed key backfill runs for that corpus
    Then the "fresh" Reference still records an accept probability of 0.4
