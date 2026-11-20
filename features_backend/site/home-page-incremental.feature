Feature: One changed Reference costs a fixed number of requests, not the size of the corpus
  The home-page snapshot used to read every accepted and every unrated Reference, then a relations request and an attachments request for each one,
  every time anything changed. On a site that takes in dozens of References an hour that was tens of thousands of AppSync requests an hour, the largest
  cost in the account. The rule is that derived work runs once when something changes, so the run now reads again only the Reference rows the stream
  trigger listed, and keeps what it knows about the others between runs.

  What it keeps is the previous public file and a private state: for each public Reference an editor's stars, the confidence the page order reads, its
  arrival time, its Reference version and its section. The state also holds the stars of pending References, which only order the page and are not shown,
  so it lives in the projection lock table and never in the public bucket (an accepted Reference's stars are published on its record; who rated it and
  when are never). When the state is missing, was built for other settings, or is not the one that goes with the file in the bucket, the run reads the whole
  corpus once and starts a new state; that is also how a site starts, once.

  The page a run produces is the page a full read would produce: the same records, the same ranks, the same file.

  Scenario Outline: A change costs the same few requests in a small corpus and in a large one
    Given a corpus of <size> References whose snapshot was built by a full read
    When an editor accepts and rates one Reference and the run reads it again
    Then the run made exactly 4 requests: one section list, the Reference, its decision and its preview
    And the full read had cost more than <size> requests

    Examples:
      | size |
      | 200  |
      | 5000 |

  Scenario: A Reference tagged with a stored section id publishes the section's title, through the full read and the incremental update
    A Reference stores its section as "publication#slug"; the section list the run reads hands the section back with its publication prefix removed,
    with the stored form beside it. The title is found by the stored form, and an id that names no section publishes no section.
    Given a corpus of 30 References whose snapshot was built by a full read
    Then the full read published the title "Articles" for the Reference tagged with the stored section id "publication#slug"
    When an editor tags one Reference with that stored section id and another with an id that names no section, and the run reads them again
    Then the tagged Reference publishes the title "Articles" and the other publishes no section

  Scenario: Ten changes cost ten times what one costs
    Given a corpus of 1000 References whose snapshot was built by a full read
    When an editor accepts 10 References and the run reads them again
    Then the run made 31 requests

  Scenario: A run with nothing listed makes no request at all
    Given a corpus of 1000 References whose snapshot was built by a full read
    When a run starts with nothing listed
    Then the run made 0 requests
    And the snapshot file is unchanged

  Scenario: A changed Reference that will not show costs no preview request and publishes nothing
    A pending Reference whose decision is below the recommended threshold is read (its row and its decision) so the run knows it is not recommended.
    Its preview, which is the third request, is never asked for.
    Given a corpus of 100 References whose snapshot was built by a full read
    When a pending Reference is retitled and the Cyclotron is only 5 percent sure of it
    Then the run made 3 requests: one section list, the Reference and its decision
    And the snapshot file is unchanged

  Scenario: A pending Reference nobody has predicted is on no page, costs one request to look at, and appears with its first prediction
    Ryan, 2026-11-05: an unpredicted Reference is not 50% and shows nothing. The run reads the Reference row, sees there is no prediction written onto it, and
    stops: it does not read its decision or its preview. When the Cyclotron's first prediction is written onto the row, that write is a change, the run reads the
    row again, and the Reference appears with whatever it holds at that moment, a stored video picture included.
    Given a corpus of 100 References whose snapshot was built by a full read
    When a pending Reference nobody has predicted is retitled and the run reads it again
    Then the run made 2 requests: one section list and the Reference
    And the snapshot file does not list that Reference
    When the Cyclotron predicts 0.8 for it, the picture of its video is stored, and the run reads it again
    Then the snapshot file lists that Reference as recommended with confidence 0.8 and its stored picture

  Scenario: State written before the rule changed is replaced by one full read, so unpredicted References already published leave
    A run reads again only the Reference rows it is given, so a Reference published under the old rule would stay. The state format is part of what the
    stored state must match, and changing it makes the next run read the whole corpus once.
    Given a corpus of 100 References whose snapshot was built under the old rule, which published Reference rows nobody had predicted
    When a run starts with one Reference listed
    Then the run read the whole corpus because the build of the fields changed
    And the snapshot file no longer lists the Reference nobody had predicted

  Scenario: The page built from changes is the page a full read builds
    Given a corpus of 300 References whose snapshot was built by a full read
    When References are accepted, rated, retitled, rejected, archived and added, one is superseded by a new version and one has been deleted
    And the run reads those rows again
    Then the snapshot file holds exactly what a full read of the same corpus would write
    And the ranks are the ranks a full read would give

  Scenario: An accepted Reference's stars are published, who rated stays out of every public file, and the private state keeps the count for the order
    Given a corpus of 90 References whose snapshot was built by a full read
    When an editor accepts one Reference with 5 stars and the run reads it again
    Then the published record of that Reference shows 5 stars
    And no published file mentions who rated or when
    And the private state holds 5 stars for that Reference

  Scenario: A change to nothing but the stars reaches the page in the incremental run
    The star count is a field the trigger watches, so a rating that changes nothing else on an accepted Reference still lists that Reference and the next run
    reads it again: the file is written with the new count, through the same four requests as any other change.
    Given a corpus of 90 References whose snapshot was built by a full read
    When an editor accepts one Reference with 5 stars and the run reads it again
    And only the stars of that Reference change and the run reads it again
    Then the published record of that Reference shows 2 stars
    And the run made exactly 4 requests: one section list, the Reference, its decision and its preview

  Scenario: Threads are read again only when a Message changed or an older Reference entered the page
    A Reference that was created after the file was last built cannot have a thread yet, so a run that only adds such References does not read the
    threads. A Message change, or an older Reference entering or leaving the page, may change a thread, so those runs read them.
    Given a corpus of 100 References whose snapshot and threads were built by a full read
    When a Reference created after the file was built is accepted and the run reads it again
    Then no thread was read
    When an older Reference is accepted and the run reads it again
    Then the threads were read
    When a run starts with a Message change listed
    Then the threads were read and no Reference was read

  Scenario: State the run cannot trust is replaced by one full read
    Given a corpus of 120 References whose snapshot was built by a full read
    When the file in the bucket is changed by someone else and a run reads one Reference
    Then the run read the whole corpus and says why
    And the next run reads only the listed Reference

  Scenario: A site's first run, a manual run and a run asked for by a mass import read the whole corpus
    Given a corpus of 120 References with no state yet
    When a run starts with one Reference listed
    Then the run read the whole corpus and says there is no state yet
    When a run starts with a full read requested
    Then the run read the whole corpus

  Scenario: A dry run saves no state
    Given a corpus of 60 References with no state yet
    When the run is a dry run
    Then no state was saved and no file was written
