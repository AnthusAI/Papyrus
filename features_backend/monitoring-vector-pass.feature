@backend @monitoring-vector-pass
Feature: The router keeps each site's vector index current and writes suggestions before it drafts ideas
  Related-Reference and concept suggestions come from comparing a Reference's stored summary vector with the vectors of the other accepted References and of the
  concepts. For that, every site's vector index has to hold a vector for each accepted Reference and a card for each accepted concept, and until now someone had to
  run the indexing by hand. Once a day the monitoring router's monitor-stories task does it for each publication, before it builds packs or drafts single items:
  first it syncs the index (the vectors of the References accepted since its last pass, and the concept cards, which cost nothing again when unchanged), then it
  suggests links for each of those newly accepted References, cut where the site's own accepted and rejected suggestions say, and only then does what it did before.
  The suggestions go in the order an editor looks at the site: first the References a person voted on or started a conversation about, newest first; then the
  pending ones (what editors triage), newest first; last the accepted ones nobody has touched, which are mostly bulk imports (drafting wants them, but an editor
  opening a Reference should find suggestions on it before a rarely opened import has them). The router keeps its place in its own table: for the pending and the
  accepted group an interval of the Reference positions (time and id) it has been through. A Reference newer than the interval is a new arrival and is done first at
  the next pass, so it never waits behind the backlog; the backlog is what is older than the interval and goes on newest first. A pass the time or cost stops
  saves exactly how far it got, the log line says how many suggestions are left, and a Reference that gains a vote after it was suggested as bulk is suggested
  again as a signal. A watermark that is a plain time, written by an older pass, means everything up to it is done. The pass is held to the first quarter of a
  publication's time so that it cannot starve the drafting, and it continues after the drafting if time is left. There is no fixed number of References or
  suggestions: the pass is bounded only by the run's time and its cost meter, to which the embeddings add their price. A site with no index
  recorded in its router entry runs without vectors, and the log line says why suggestions are off. The index addresses and storage buckets are copied from each
  site's amplify_outputs.json when the router configuration is seeded, never typed. The index, the embeddings and the backends are fakes in these scenarios.

  Scenario: References newer than an older pass's watermark are the new arrivals, done oldest of them first, and the saved place moves
    Given a publication with an index whose watermark is "2026-10-29T12:00:00Z"
    And References accepted at "2026-10-29T10:00:00Z", "2026-10-30T10:00:00Z" and "2026-10-31T10:00:00Z"
    When the vector pass runs
    Then the index is synced for the 2 References accepted after the watermark before any suggestion is made
    And suggestions are made for "ref-2" and "ref-3" only
    And the saved place for accepted References runs from nothing older to "ref-3"

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

  Scenario: With no saved place the newest References come first, and a pass the time stopped saves how far it got
    Given a publication with an index and no saved place
    And References accepted at "2026-10-30T10:00:00Z", "2026-10-30T11:00:00Z" and "2026-10-30T12:00:00Z"
    And the time lasts for the index sync and 1 suggestion
    When the vector pass runs
    Then the pass was stopped by time
    And suggestions are made for "ref-3" only
    And 2 suggestions are left
    And the saved place for accepted References runs from "ref-3" to "ref-3"

  Scenario: The next pass goes on below the saved place and finishes
    Given a publication whose saved place for accepted References runs from "ref-3" to "ref-3"
    And References accepted at "2026-10-30T10:00:00Z", "2026-10-30T11:00:00Z" and "2026-10-30T12:00:00Z"
    When the vector pass runs
    Then suggestions are made for "ref-2" and "ref-1" only
    And no suggestions are left
    And the saved place for accepted References runs from "ref-1" to "ref-3"

  Scenario: A Reference that arrives while the backlog is unfinished is handled first at the next pass
    Given a publication whose saved place for accepted References runs from "ref-3" to "ref-3"
    And References accepted at "2026-10-30T10:00:00Z", "2026-10-30T11:00:00Z" and "2026-10-30T12:00:00Z"
    And a Reference "ref-4" accepted at "2026-10-31T10:00:00Z" has arrived
    When the vector pass runs
    Then suggestions are made for "ref-4", "ref-2" and "ref-1" only
    And the saved place for accepted References runs from "ref-1" to "ref-4"

  Scenario: References that share one acceptance time, as in a bulk import, are told apart by their id
    Given a publication with an index and no saved place
    And References accepted at "2026-10-30T10:00:00Z", "2026-10-30T10:00:00Z" and "2026-10-30T10:00:00Z"
    And the time lasts for the index sync and 2 suggestions
    When the vector pass runs
    Then 1 suggestion is left
    And the saved place for accepted References runs from "ref-2" to "ref-3"

  Scenario: What an editor looks at comes first
    Given a publication with an index and no saved place
    And References accepted at "2026-10-30T10:00:00Z", "2026-10-30T11:00:00Z", "2026-10-30T12:00:00Z" and "2026-10-31T10:00:00Z"
    And an editor voted on "ref-1"
    And a conversation is anchored on "ref-2"
    And a pending Reference with id "ref-9" changed at "2026-10-30T09:00:00Z"
    When the vector pass runs
    Then suggestions are made in the order "ref-2", "ref-1", "ref-9", "ref-4", "ref-3"

  Scenario: A Reference that gains a vote after it was suggested as bulk is suggested again
    Given a publication with an index and no saved place
    And References accepted at "2026-10-30T10:00:00Z" and "2026-10-30T11:00:00Z"
    When the vector pass runs
    And an editor voted on "ref-1"
    And the vector pass runs
    Then suggestions are made for "ref-1" only

  Scenario: A large backlog of vectors does not stop the drafting
    Given a router publication whose entry names an index and a storage bucket
    And 2 accepted References that the "hn" monitor delivered, one accepted since the last pass
    And the vector pass's share of the time is already spent
    When the router runs its daily monitor stories with the vector pass
    Then the steps ran in the order index sync, drafting, index sync, suggestions
    And 2 ideas are drafted
    And the log line shows no raised curation flag

  Scenario: When the drafting is done with time to spare, the vector pass continues from where it stopped
    Given a router publication whose entry names an index and a storage bucket
    And 2 accepted References that the "hn" monitor delivered, one accepted since the last pass
    And the vector pass's share of the time is already spent
    When the router runs its daily monitor stories with the vector pass
    Then the log line says 2 suggestions written and no suggestions left

  Scenario: The router holds the vector pass to the first quarter of a publication's time
    Given the router has 400 seconds left when a publication starts
    When the router runs its daily monitor stories with a fake drafter
    Then drafting is out of time at 120 seconds left and the vector pass at 330 seconds left

  Scenario: Concept cards and concept suggestions leave out authors and the graph's own bookkeeping
    Given a site whose graph has the concepts "voice cloning" (task) and "pitch" (concept), an author, a coverage question, a comment concept, a quality rating and a relevance decision
    When the concept cards are prepared
    Then only "voice cloning" and "pitch" have a card
    And a card for an author that was written earlier is not offered as a suggested concept

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

  Scenario: Texts the embeddings endpoint would refuse are dropped or cut, and a refusal says why
    Given a batch of texts to embed with one empty text, one whitespace-only text and one longer than the input limit
    When the batch is embedded
    Then the empty and whitespace-only texts are dropped and counted
    And the long text is cut to a safe length and counted
    And a request the endpoint refuses with 400 fails with the endpoint's own message and never the key
