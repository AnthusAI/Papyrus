Feature: Context packs from the newsroom's own activity, and no repeat without new evidence
  The newsroom surfaces themes from what people do: a conversation that lights up on a Reference, and a concept whose References editors
  accept faster than usual. Each theme becomes a context pack, built by code from one read of the publication. A signal compares an entity with its
  own earlier history against the whole site (conversations by the day, accepts by the week), corrects for the number of windows tried, and
  reports a pack only when the activity is surprising; there is no fixed window or cap. Pending References appear in a pack as context marked
  "not yet accepted" and can never be cited as evidence. Packs from different signals are interleaved by surprise, and a pack is trimmed only to the
  model's input size. An idea records the pack's anchor, and the same anchor is offered again only with new evidence: materially more activity
  than the idea reported, or an accepted Reference it did not hold; the anchor of a spiked idea needs both.

  Two more signals read the graph of References. A hub is a recently arrived Reference with far more connections (current edges, and shared
  concepts weighted by how rare they are) than the rest of the site; a cluster is a group of recently accepted References joined by current edges
  and by mutual nearest neighbours in the vector index. When an entity's own history is shorter than the minimum baseline (a young site), its
  count is compared with its expected share among the site's comparable entities instead, and the pack is marked emerging; a group with no
  earlier arrivals is new and also emerging. Without a vector index the cluster signal is skipped and the log says why. Pack edges tell the
  links people confirmed from the ones only the vectors suggest.

  The monitoring router runs all of this once a day for each publication. It reads the publication once, builds and ranks the packs, scores the
  single-item candidates from the same signals, and walks ONE queue in which packs and single items take turns by surprise. A pack goes to the
  idea agent, which proposes between one and three ideas about the theme; a single item goes to the single-item path. Both share one cost meter and
  the same stops (the Lambda's time, the model-spend backstop and a filing error), every idea passes the same editorial gate, and one soft review
  request covers the whole run. A publication sets `singleItem` and `contextPacks` (`enabled`, and optionally the `signals` to use) in its router
  entry; there is no numeric setting. Its log line reports the packs offered, the ideas they produced, the packs held back for want of new
  evidence, and for each pack the signal, the anchor and the corrected p-value.

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

  Scenario: A pack yields up to three ideas that each cite at least two accepted References
    Given an acceptance pack and a model that proposes an idea citing two accepted References and a concept
    When the pack ideas are drafted
    Then one idea is filed at the idea stage with a based_on link for each cited Reference
    And the idea records the context-pack origin and the pack evidence
    And the idea is linked to the concept with a derived related_to edge
    And the idea body ends with an Evidence section

  Scenario: An idea that cites one Reference is dropped and the pack goes on
    Given an acceptance pack and a model that proposes one idea citing a single Reference and one citing two
    When the pack ideas are drafted
    Then one idea is filed and one idea is dropped for failing the citation check

  Scenario: An idea that cites a pending Reference is dropped
    Given an acceptance pack and a model that proposes an idea citing a pending Reference
    When the pack ideas are drafted
    Then no idea is filed and the idea is dropped for citing a pending Reference

  Scenario: An idea the editorial gate refuses is not filed
    Given an acceptance pack and a model that proposes an idea citing two accepted References
    And an editorial gate that finds an error in the idea
    When the pack ideas are drafted
    Then no idea is filed and one idea is refused

  Scenario: A dry run writes nothing
    Given an acceptance pack and a model that proposes an idea citing two accepted References
    When the pack ideas are drafted as a dry run
    Then no idea is filed and nothing is written

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

  Scenario: A pack yields at most three ideas and each cites at least two accepted References
    Given an acceptance pack and a model that proposes four ideas that each cite two accepted References
    When the pack ideas are drafted
    Then three ideas are filed and one idea is dropped for being the fourth
    And every filed idea cites at least two accepted References

  Scenario: Every idea a pack files sits in the Idea stage and passed the editorial gate first
    Given an acceptance pack and a model that proposes an idea citing two accepted References
    And an editorial gate that finds nothing
    When the pack ideas are drafted
    Then the editorial gate checked the idea before it was filed
    And the filed idea sits in the Idea stage

  Scenario: One run walks one queue of packs and single items and raises one review
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    When the monitor-stories task runs
    Then the model is asked about the pack before the single item
    And the pack's ideas and the single item's idea are all filed
    And one review request covers the run

  Scenario: The log line says what the packs did
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    When the monitor-stories task runs
    Then the log line counts one pack and the two ideas it produced
    And the log line names the pack's signal, anchor and corrected p-value
    And the log line counts no pack held back for want of new evidence

  Scenario: A pack whose anchor already has an idea is not drafted again without new evidence
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And an idea that was drafted from that pack on an earlier run
    When the monitor-stories task runs
    Then the model is not asked about the pack
    And the log line counts one pack held back for want of new evidence

  Scenario: A publication can ask for packs only
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And the publication sets singleItem to false
    When the monitor-stories task runs
    Then only the pack's ideas are filed

  Scenario: A publication can turn context packs off and keep the single-item task
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And the publication turns context packs off
    When the monitor-stories task runs
    Then no pack is built and only single items are drafted

  Scenario: A publication can name the signals its packs come from
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And the publication names only the conversation signal
    When the monitor-stories task runs
    Then no acceptance pack is drafted

  Scenario: A run that runs out of time after the pack keeps the pack's ideas and stops
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And the Lambda runs out of time as soon as the pack has been drafted
    When the monitor-stories task runs
    Then the publication is stopped by time with the pack's ideas filed and no single item drafted

  Scenario: A filing error on a pack idea stops the publication before more money is spent
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And filing a pack idea fails with a missing grant
    When the monitor-stories task runs
    Then the publication is stopped by the filing error and the single item is not asked for

  Scenario: Packs and single items spend from one budget
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    And a model-spend backstop that the pack's call nearly uses up
    When the monitor-stories task runs
    Then the publication is stopped by cost after the pack and the single item is not asked for

  Scenario: A dry run of the command prints the packs and writes nothing
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    When the monitor-stories command runs as a dry run
    Then the output lists the pack with its signal, anchor, corrected p-value and date basis
    And no idea is filed and no review is requested

  Scenario: The command can be asked for packs only or single items only
    Given a publication with a concept whose accepts jump and a monitored Reference with a lively thread
    When the monitor-stories command runs as a dry run with packs only
    Then the model is asked only about the pack
    When the monitor-stories command runs as a dry run with single items only
    Then the model is asked only about single items and no pack is listed

  Scenario: A lively thread on one Reference yields a pack with the related accepted References and an idea
    Given a lively thread on one Reference whose concept has other accepted References
    When the context packs are built and the pack ideas are drafted
    Then the conversation pack holds the anchor first and the related accepted References marked with their shared concept
    And one idea is filed citing two accepted References

  Scenario: A cold site with no concept links still yields a cluster pack from vectors alone
    Given a site five days old whose accepted References have no concept links and no edges, four of them about one thing
    When the context packs are built with the site's vector index
    Then a cluster pack holds those four accepted References
    And the pack is marked emerging because no earlier arrivals exist to compare with
    And the pack's edges are all suggested and each carries its similarity

  Scenario: A confirmed edge and a suggested one are told apart in a pack
    Given a site five days old whose accepted References have no concept links and no edges, four of them about one thing
    And a person has linked two of them with a related_to edge
    When the context packs are built with the site's vector index
    Then the cluster pack lists that link as confirmed without a similarity
    And the other pairs are listed as suggested with their similarity

  Scenario: Without a vector index the cluster signal is skipped and says why
    Given a site five days old whose accepted References have no concept links and no edges, four of them about one thing
    When the context packs are built without a vector index
    Then no cluster pack exists
    And the log says the cluster signal was skipped for want of a vector provider

  Scenario: A cold site whose References are alike yields no cluster pack
    Given a site five days old whose accepted References have no concept links and no edges, none of them alike
    When the context packs are built with the site's vector index
    Then no pack exists

  Scenario: A Reference with far more connections than the rest of the site is a hub
    Given a site of 150 accepted References where the newest one is linked to six older ones
    When the context packs are built
    Then a hub pack exists for the newest Reference
    And the hub's degree is six and its percentile is the share of the site's References that have as many connections
    And its neighbours are marked as linked and their edges as confirmed

  Scenario: A young thread is compared with the site's other threads when its own history is too short
    Given six quiet threads and one loud thread, all less than two days old
    When the context packs are built
    Then a conversation pack exists for the loud thread
    And the pack is marked emerging and says it was compared with the site's other threads

  Scenario: Threads that all speak at the same rate yield nothing even when every thread is young
    Given six threads of three Messages each, all less than two days old
    When the context packs are built
    Then no pack exists

  Scenario: A conversation pack holds the References linked to its anchor
    Given a lively thread on a Reference that a machine-accepted Reference cites
    When the context packs are built from those inputs
    Then the conversation pack holds the cited Reference marked linked with a confirmed edge
