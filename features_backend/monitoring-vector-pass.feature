@backend @monitoring-vector-pass
Feature: The router keeps each site's vector index current by reading only what changed, and never walks the site to find work
  Related-Reference and concept suggestions come from comparing a Reference's stored summary vector with the vectors of the other accepted References and of the
  concepts, so every site's vector index has to hold a vector for each accepted or pending Reference and a card for each accepted concept. Once a day the monitoring
  router's monitor-stories task brings the index up to date before it builds packs or drafts single items. The pass is proportional to what changed since it last
  ran, not to the size of the site: it asks the updatedAt indexes of the Reference table and of the concept table for the rows changed since its saved place (one
  read of up to a thousand rows each, oldest first) and hands only those rows to the indexer. For each changed Reference the indexer looks up its summary vector by
  key; it never lists the Reference table, the vectors of the index, the concepts or the links. A vote, a star or a retitle changes a row's updatedAt too, and finds
  its vector as it is, so it writes nothing. A Reference accepted or sent back to pending has its stored status rewritten without a new embedding, and one rejected or
  archived loses its vectors, found by a query filtered to that Reference. A Reference whose summary vector is stored, new or rewritten because its text changed, makes
  one related-items check (features_backend/suggest-once.feature); the pass has no suggestion step of its own. The router keeps its place in its own table: the
  newest updatedAt it has indexed and the ids of the rows within ten minutes of it, so a row written late with an earlier clock is still read once and a row already
  done is not read twice. A page moves the place as soon as it is done, so a run the time or the cost stops resumes exactly there. A site with no saved place is
  indexed once by the full sync, and the place is set to the newest change read before it began. Link explanations have no changed-since index and are left to the
  command-line sync. The only bounds are the run's time and its cost meter. The index, the embeddings and the backends are fakes in these scenarios.

  Scenario: A site with nothing new makes one read per change feed and nothing else
    Given a site of 2000 References that are all indexed, with the pass up to date
    When the vector pass runs
    Then the pass made 2 requests to the API, none to the vector index and none for text
    And the pass reports 0 changed References
    And no saved place is written

  Scenario: The requests grow with what changed and not with the size of the site
    Given a site of 200 References that are all indexed, with the pass up to date
    And a site of 5000 References that are all indexed, with the pass up to date
    And 3 References on each were voted on or starred
    When the vector pass runs on both
    Then each pass made 5 requests to the API: 2 reads of the change feeds and 3 reads of attachments
    And each pass made the same number of requests to the vector index and embedded nothing

  Scenario: A new Reference is embedded once and its summary vector is announced once
    Given a site of 100 References that are all indexed, with the pass up to date
    And 2 new References have arrived
    When the vector pass runs
    Then the 2 new References have a summary vector and each was announced once
    When the vector pass runs
    Then nothing is announced again

  Scenario: A vote or a star neither embeds nor announces
    Given a site of 2 References that are all indexed, with the pass up to date
    And an editor starred a Reference
    When the vector pass runs
    Then nothing was embedded and nothing was announced

  Scenario: Accepting a pending Reference rewrites its stored status without a new embedding or a new check
    Given a pending Reference that is indexed
    And an editor accepted it
    When the vector pass runs
    Then its summary vector is marked accepted with the same vector data, its passages are written and nothing was announced

  Scenario: Rejecting a Reference deletes its vectors without listing the index
    Given an accepted Reference that is indexed and another that is not rejected
    And an editor rejected the first
    When the vector pass runs
    Then the first has no vector, the other keeps its vectors and the index was not listed

  Scenario: Changed text stores the summary vector again and announces it with the new hash
    Given a pending Reference whose summary vector was made from its summary alone
    When the vector pass runs
    And the summary is rewritten and the vector pass runs
    Then the Reference was announced twice with two different hashes

  Scenario: A site with no saved place is indexed once by the full sync
    Given a site with 3 References and no saved place
    When the vector pass runs
    Then the full sync ran once with link explanations and notes left out
    And the saved place is the newest change read before the sync began

  Scenario: A pass the time stops resumes where its last finished page ended
    Given a site with 7 References changed since the saved place, read 2 to a page
    And the time runs out while the second page is being indexed
    When the vector pass runs
    Then the saved place is the end of the first page
    When the vector pass runs with time to spare
    Then the saved place is the newest change and every Reference was announced

  Scenario: A site with no index in its router entry runs without vectors and says why
    Given a site with 1 Reference and a saved place
    And the publication has no vector index recorded
    When the vector pass runs
    Then the reason says there is no vectorIndexArn in the publication's monitorStories
    And the pass made 0 requests to the API

  Scenario: Suggestions can be turned off for a publication while its index is still kept current
    Given a site with 1 Reference and a saved place
    And suggestions are off for the publication
    When the vector pass runs
    Then the Reference is indexed, nothing is announced and the reason says suggestions are off

  Scenario: The pass has no suggestion step, no plan and no backlog
    Then the vector pass module has no plan, no owed memory, no suggestion step and no backlog task
    And the monitoring template has no suggest-backlog schedule

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

  Scenario: Concept cards and concept suggestions leave out authors and the graph's own bookkeeping
    Given a site whose graph has the concepts "voice cloning" (task) and "pitch" (concept), an author, a coverage question, a comment concept, a quality rating and a relevance decision
    When the concept cards are prepared
    Then only "voice cloning" and "pitch" have a card
    And a card for an author that was written earlier is not offered as a suggested concept
