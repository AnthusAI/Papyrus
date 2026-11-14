@backend @reference-feed-keys
Feature: The References page pages through two indexes whose keys every writer keeps right
  The newsroom References page used to download every Reference, every attachment and every decision, and rank them in the browser. It
  now asks for one page at a time from one of two indexes on the Reference itself. Both are partitioned by a feed state: a Reference that
  nobody has voted on is in the unrated feed of its corpus, one that is accepted or rejected is in the rated feed, and one that is archived
  or is no longer the current version is in neither. "Predictions" is sorted by the Cyclotron's original chance that the editor accepts
  (P of accept), highest first, then newest first. "Newest" is sorted by when the Reference arrived. The prediction is a value written on
  the Reference once, when the Cyclotron first decides it. It is the confidence of the include label, or one minus the confidence of the
  exclude label. A Reference nobody has predicted sorts as one half, after every predicted Accept and before every predicted Reject. A vote
  moves a Reference between the feeds and never touches its prediction. Nothing here touches production: the backend is in memory.

  Scenario: Recording a prediction writes the original accept confidence onto the Reference
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    When the Cyclotron decides "include" with 91% confidence and the publication's positive label is "include"
    Then the Reference records an accept probability of 0.91
    And the Reference records when the Cyclotron decided it
    And its Predictions key is "0.910000#2026-10-28T12:00:00.000Z#" followed by its id
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
    When their Predictions keys are read highest first
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
    And its Predictions key is unchanged

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

  Scenario: A star rating puts the Reference in the star partition for its stars and clearing it takes it out
    The Quality sort and the minimum-stars choice read a third index, partitioned by "<corpus>#stars#<n>" and sorted by arrival. It is sparse:
    a Reference with no stars is in no partition. The key is written with the rating, never with the feed keys, so a write that carries
    the feed keys alone cannot clear it.
    Given a pending Reference that arrived at "2026-10-28T12:00:00Z" and has no prediction
    When an editor's rating of 4 stars is recorded on it
    Then it is in the star partition for 4 stars of its corpus
    When an editor's rating of 2 stars is recorded on it
    Then it is in the star partition for 2 stars of its corpus
    When the editor's rating is cleared on it
    Then it is in no star partition of its corpus
    And the feed keys of a Reference never include the star key

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

  Scenario: The backfill puts a starred Reference in its star partition
    The Quality sort and the minimum-stars choice read the star index, one partition per star level, "<corpus>#stars#<n>". A Reference starred
    before that index existed has no star key, so the backfill sets it from the stars the Reference already records. One without stars gets none.
    Given a corpus with these References and no feed keys
      | name    | status   | decision |
      | picked  | pending  | none     |
      | voted   | accepted | none     |
      | plain   | pending  | none     |
    And the "picked" Reference is starred 4 stars
    And the "voted" Reference is starred 5 stars
    When the feed key backfill runs for that corpus
    Then the "picked" Reference is in the star partition "stars#4"
    And the "voted" Reference is in the star partition "stars#5"
    And the "plain" Reference is in no star partition
    And the backfill reports 2 star keys changed
    And each backfill write names only the Reference id and feed key fields

  Scenario: The backfill clears a star key whose stars are gone and writes nothing the second time
    Given a corpus with these References and no feed keys
      | name    | status  | decision |
      | cleared | pending | none     |
      | picked  | pending | none     |
    And the "picked" Reference is starred 3 stars
    And the "cleared" Reference still has the star key "stars#2" though it has no stars
    When the feed key backfill runs for that corpus
    And the feed key backfill runs for that corpus again
    Then the "cleared" Reference is in no star partition
    And the "picked" Reference is in the star partition "stars#3"
    And the second run wrote nothing

  Scenario Outline: Every way of creating a Reference is in the feed
    The feed reads References only through their feed keys, so a Reference created without them would be invisible there. Whatever the
    source of a new Reference (a monitor, an editor's console, an email, a chat message, the command line, an import, an accession or a
    citation in a paper) and whichever publication it is for, it starts out pending, so it must be in the unrated feed of its own corpus
    the moment it exists. It has an arrival time and sorts as one half until the Cyclotron decides it.

    Given a publication whose corpus key is "<corpus>"
    When a Reference is created by "<path>"
    Then the new Reference is in the unrated feed of "<corpus>"
    And the new Reference has an arrival time and sorts as one half

    Examples:
      | path                                              | corpus     |
      | papyrus references import (CLI)                   | alpha-site |
      | papyrus references import (CLI)                   | beta-site  |
      | monitor delivery                                  | alpha-site |
      | monitor delivery                                  | beta-site  |
      | email submission                                  | alpha-site |
      | email submission                                  | beta-site  |
      | named import (cursor:...)                         | alpha-site |
      | Slack / console chat Reference.create             | alpha-site |
      | Slack / console chat Reference.create             | beta-site  |
      | console intake mutation (intakePendingReferences) | alpha-site |
      | console intake mutation (intakePendingReferences) | beta-site  |
      | GROBID cited reference                            | alpha-site |
      | GROBID cited reference                            | beta-site  |
      | accession replacement                             | alpha-site |
      | accession next version                            | beta-site  |

  Scenario: A new version of a Reference stays in the feed with its original prediction and arrival
    Given a corpus whose References have these versions
      | version | arrived                  | accept probability |
      | 1       | 2026-11-01T00:00:00.000Z | 0.9                |
    When the Reference is imported again with a changed title
    Then the first version is in no feed
    And the second version is in the unrated feed
    And the second version still records an accept probability of 0.9 and the arrival "2026-11-01T00:00:00.000Z"

  Scenario: A new version of a Reference keeps the stars an editor gave it
    Given a corpus whose References have these versions
      | version | arrived                  | accept probability |
      | 1       | 2026-11-01T00:00:00.000Z | 0.9                |
    And an editor gave the first version 5 stars
    When the Reference is imported again with a changed title
    Then the second version still has 5 stars and is in the 5-star partition

  Scenario Outline: A vote from a chat message moves the Reference between the feeds
    Given a pending Reference in a corpus
    When a chat message asks to "<action>" it
    Then the vote is written with feed state "<feed>"

    Examples:
      | action  | feed     |
      | accept  | rated    |
      | reject  | rated    |
      | reopen  | unrated  |
      | archive | no feed  |

  Scenario: One backfill run covers every corpus of a publication
    Given a backend with a pending Reference with no feed keys in each of the corpora "alpha-site", "beta-site" and "gamma-site"
    When the feed key backfill runs for all corpora
    Then the backfill covered 3 corpora
    And each Reference is in the unrated feed of its own corpus

  Scenario: A backfill run can be limited to named corpora
    Given a backend with a pending Reference with no feed keys in each of the corpora "alpha-site", "beta-site" and "gamma-site"
    When the feed key backfill runs for the corpus keys "alpha-site,beta-site"
    Then the backfill covered 2 corpora
    And the "gamma-site" corpus Reference still has no feed keys
