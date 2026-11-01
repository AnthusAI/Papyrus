Feature: Context packs from the newsroom's own activity, and no repeat without new evidence
  The newsroom surfaces themes from what people do: a conversation that lights up on a Reference, and a concept whose References editors
  accept faster than usual. Each theme becomes a context pack, built by code from one read of the publication. A signal compares an entity with its
  own earlier history against the whole site (conversations by the day, accepts by the week), corrects for the number of windows tried, and
  reports a pack only when the activity is surprising; there is no fixed window or cap. Pending References appear in a pack as context marked
  "not yet accepted" and can never be cited as evidence. Packs from different signals are interleaved by surprise, and a pack is trimmed only to the
  model's input size. An idea records the pack's anchor, and the same anchor is offered again only with new evidence: materially more activity
  than the idea reported, or an accepted Reference it did not hold; the anchor of a spiked idea needs both.

  Scenario: A thread that lights up yields a conversation pack
    Given a thread with nine Messages today after weeks of quiet
    When the context packs are built
    Then a conversation pack exists for that thread
    And the pack states that its dates are Message dates

  Scenario: A concept at its own baseline yields no pack
    Given a concept whose References are accepted at a steady rate
    When the context packs are built
    Then no pack exists

  Scenario: A site with no Messages still yields acceptance packs
    Given a concept whose accepts jump in the latest week
    When the context packs are built
    Then an acceptance pack exists for that concept
    And the pack states that its dates are ingestion dates

  Scenario: A pending Reference is context and never evidence
    Given a concept whose accepts jump in the latest week
    And a pending Reference that mentions the concept
    When the context packs are built
    Then the pack lists the pending Reference with a P handle marked "not yet accepted"
    And the pending Reference is not among the pack's accepted References

  Scenario: An anchor already drafted yields nothing without new evidence
    Given a concept whose accepts jump in the latest week
    And an idea that was drafted from that pack
    When the context packs are built and repeats are suppressed
    Then no pack is offered and one pack is counted as skipped for no new evidence

  Scenario: A new accepted Reference makes the anchor eligible again
    Given a concept whose accepts jump in the latest week
    And an idea that was drafted from that pack without its last accepted Reference
    When the context packs are built and repeats are suppressed
    Then the pack is offered again

  Scenario: A spiked idea's anchor needs both new activity and a new Reference
    Given a concept whose accepts jump in the latest week
    And a spiked idea that was drafted from that pack without its last accepted Reference
    When the context packs are built and repeats are suppressed
    Then no pack is offered and one pack is counted as skipped for no new evidence

  Scenario: A Reference no monitor delivered, with a lively thread, outranks a quiet monitored one
    Given a site whose accepted References are mostly quiet
    And an accepted Reference no monitor delivered, with a lively thread of Messages
    And an accepted Reference a monitor delivered, with no activity
    When the single-item candidates are scored
    Then the Reference with the lively thread is the first candidate
    And the quiet monitored Reference is not a candidate

  Scenario: A quiet site yields no single-item candidate
    Given a site whose accepted References are mostly quiet
    And an accepted Reference a monitor delivered, with no activity
    When the single-item candidates are scored
    Then there are no single-item candidates

  Scenario: Packs and single items share one queue
    Given a site whose accepted References are mostly quiet
    And an accepted Reference no monitor delivered, whose thread lights up after weeks of quiet
    When the packs and the single-item candidates are queued together
    Then the queue holds both a pack and a single item
