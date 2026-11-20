Feature: Repeated copies of the same email submission are one item with one decision
  People forward the same newsletter more than once. Each forward is a separate delivery with
  its own receipt, so editors used to see the same email several times. The receiver now
  fingerprints each message by its normalized subject and its set of extracted links, so the
  Monitoring list shows one item per email with "received N times" and the dates, and a single
  Accept or Reject applies to every copy. A copy that arrives after the decision takes the same
  decision without asking again. Link import stays keyed by canonical URL, so grouped copies never
  create duplicate References.

  Scenario: Three copies of one forwarded newsletter are listed as one item
    Given the same newsletter was received three times, once as a "Fwd:" forward
    When an editor opens the Monitoring email list
    Then the list shows one item that was received 3 times
    And expanding it shows all 3 copies with their dates

  Scenario: Different emails are never grouped
    Given the same newsletter was received three times, once as a "Fwd:" forward
    And an email with the same subject but a different link was received
    And an email with a different subject but the same links was received
    When an editor opens the Monitoring email list
    Then the list shows 3 items

  Scenario: One decision covers every copy
    Given the same newsletter was received three times, once as a "Fwd:" forward
    When an editor accepts the newsletter once with a reason
    And the receiver applies the recorded decisions
    Then every copy records the same actor, time and reason, referencing the group decision
    And every copy is released and queued
    And a second, opposite decision from any copy is refused

  Scenario: A copy that was already decided keeps its decision
    Given the same newsletter was received three times, once as a "Fwd:" forward
    And the oldest copy was rejected on its own before the group was decided
    When an editor accepts the newsletter once with a reason
    And the receiver applies the recorded decisions
    Then the oldest copy stays rejected and the other copies are released

  Scenario: A late copy of an accepted email inherits the accept
    Given the same newsletter was received three times, once as a "Fwd:" forward
    And an editor accepted the newsletter and the receiver applied it
    When a fourth copy of the newsletter arrives
    Then the fourth copy takes the accept without any new question
    And its links are queued

  Scenario: A late copy of a rejected email is closed
    Given the same newsletter was received three times, once as a "Fwd:" forward
    And an editor rejected the newsletter and the receiver applied it
    When a fourth copy of the newsletter arrives that passes authentication
    Then the fourth copy is closed and nothing is routed

  Scenario: Grouped copies never create duplicate References
    Given the same newsletter was received three times, once as a "Fwd:" forward
    And an editor accepted the newsletter and the receiver applied it
    When the same article link is imported from each copy
    Then only one Reference request exists for that canonical URL

  Scenario: Receipts stored before grouping are fingerprinted without changing their data
    Given the same newsletter was received three times, once as a "Fwd:" forward
    And the receipts have no fingerprint, as before this feature
    When the receiver runs the fingerprint backfill task
    Then the three receipts are grouped and no other receipt field changed
