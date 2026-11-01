@backend @monitoring-vector-pass
Feature: The router keeps each site's vector index current and writes suggestions before it drafts ideas
  Related-Reference and concept suggestions come from comparing a Reference's stored summary vector with the vectors of the other accepted References and of the
  concepts. For that, every site's vector index has to hold a vector for each accepted Reference and a card for each accepted concept, and until now someone had to
  run the indexing by hand. Once a day the monitoring router's monitor-stories task does it for each publication, before it builds packs or drafts single items:
  first it syncs the index (the vectors of the References accepted since its last pass, and the concept cards, which cost nothing again when unchanged), then it
  suggests links for each of those newly accepted References, cut where the site's own accepted and rejected suggestions say, and only then does what it did before.
  The router remembers "since the last pass" as the newest acceptance time it finished, in its own table next to its other per-publication state, so a pass
  that is stopped leaves it where it was and the next pass takes up the same References again; vectors already written are skipped. There is no fixed number of
  References or suggestions: the pass is bounded only by the run's time and its cost meter, to which the embeddings add their price. A site with no index
  recorded in its router entry runs without vectors, and the log line says why suggestions are off. The index addresses and storage buckets are copied from each
  site's amplify_outputs.json when the router configuration is seeded, never typed. The index, the embeddings and the backends are fakes in these scenarios.

  Scenario: A pass syncs the index for the newly accepted References, then suggests, then the watermark moves
    Given a publication with an index whose watermark is "2026-10-29T12:00:00Z"
    And References accepted at "2026-10-29T10:00:00Z", "2026-10-30T10:00:00Z" and "2026-10-31T10:00:00Z"
    When the vector pass runs
    Then the index is synced for the 2 References accepted after the watermark before any suggestion is made
    And suggestions are made for those 2 References, the older first
    And the watermark is now "2026-10-31T10:00:00Z"

  Scenario: A pass with nothing new still syncs the concept cards and writes no suggestions
    Given a publication with an index whose watermark is "2026-10-31T10:00:00Z"
    And References accepted at "2026-10-30T10:00:00Z"
    When the vector pass runs
    Then the index is synced for the concept cards only
    And no suggestion is made

  Scenario: A site with no index in its router entry runs without vectors and says why
    Given a publication with no index recorded
    And References accepted at "2026-10-30T10:00:00Z"
    When the vector pass runs
    Then nothing is indexed and no suggestion is made
    And the reason says there is no vectorIndexArn in the publication's monitorStories
    And no watermark is written

  Scenario: Suggestions can be turned off for a publication while its index is still kept current
    Given a publication with an index whose watermark is "2026-10-29T12:00:00Z"
    And suggestions are off for the publication
    And References accepted at "2026-10-30T10:00:00Z"
    When the vector pass runs
    Then the index is synced for the 1 References accepted after the watermark before any suggestion is made
    And no suggestion is made
    And the reason says suggestions are off

  Scenario: The price of the embeddings is on the run's cost meter and can stop the pass
    Given a publication with an index whose watermark is "2026-10-29T12:00:00Z"
    And the sync embeds 400 million characters
    And References accepted at "2026-10-30T10:00:00Z"
    When the vector pass runs
    Then the pass was stopped by cost
    And no suggestion is made
    And no watermark is written

  Scenario: A pass that runs out of time keeps its watermark so the next pass takes up the same References
    Given a publication with an index whose watermark is "2026-10-29T12:00:00Z"
    And References accepted at "2026-10-30T10:00:00Z"
    And the run is out of time
    When the vector pass runs
    Then the pass was stopped by time
    And no watermark is written

  Scenario: The router's run indexes, suggests and then drafts, and its log line says what was done
    Given a router publication whose entry names an index and a storage bucket
    And 2 accepted References that the "hn" monitor delivered, one accepted since the last pass
    When the router runs its daily monitor stories with the vector pass
    Then the steps ran in the order index sync, suggestions, drafting
    And the log line says 3 vectors indexed, 1 concept cards written, 2 suggestions written and no suggestions reason
    And the router's table holds the watermark of the publication

  Scenario: A router run without an index still drafts and the log line says suggestions are off
    Given a router publication whose entry names no index
    And 2 accepted References that the "hn" monitor delivered, one accepted since the last pass
    When the router runs its daily monitor stories without an index
    Then 2 ideas are drafted
    And the log line says 0 vectors indexed, 0 concept cards written, 0 suggestions written and the reason that there is no vectorIndexArn

  Scenario: Seeding copies each site's index address and storage bucket from its amplify_outputs.json
    Given the example router configuration and the amplify_outputs.json of "anth-us"
    When the vector settings are filled from the outputs
    Then the "anth-us" entry carries the index address and the storage bucket from its outputs
    And the other entries are unchanged
    And outputs without an index address are refused

  Scenario: The router package carries the vector pass and the knowledge-query package it runs
    Given the router package modules computed from this repository
    Then they include the vector pass, the suggestions and the calibration
    And the knowledge-query package files are added to the package without its command line
