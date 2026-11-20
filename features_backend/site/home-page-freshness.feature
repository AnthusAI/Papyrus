Feature: Curation changes reach the home-page pages by themselves, in one debounced run
  A site that turns on the home-page plugin does not wait for someone to run a command. Every change to a Reference that a
  public page shows or ranks by (its curation status, its place in the feed, its prediction, its version state, its title, its
  section or an editor's star rating, which orders the pages and is printed on an accepted Reference's tile; who rated and when are not watched) arrives on the Reference table's DynamoDB stream. A small trigger function turns a burst of such changes into
  one home-page-snapshot run at the end of a quiet window: the first change opens the window and schedules the run, the
  changes that follow inside the window find it open and schedule nothing, but each adds the id of its Reference to a list the run reads, so
  the run reads again those rows and no others (home-page-incremental.feature). A Reference that no page can show, for example a new pending one
  nobody has predicted, changes nothing and runs nothing. The run writes the snapshot only when it changed and re-renders only the pages that read the
  changed selection.

  When the site shows Message threads (homePage.threads.enabled), the Message table's stream feeds the same trigger. A new
  comment, or a change to a comment's status, text, edit time or deletion time, opens the same window, so one run refreshes the
  References and the threads together. A site that already streams its Messages for another feature has that stream reused.

  A person who posts to a forum is waiting to see the post, so a changed Message does not wait for the Reference window: it opens a
  window of its own, homePage.freshness.threadDebounceSeconds (3 seconds by default), and the Message stream hands the trigger a record as soon
  as it arrives. The run that window schedules also takes every Reference id listed by then. The pages it writes are cached at the edge only
  as long as publication.cache.liveSMaxAgeSeconds (projection-publish.feature).

  The plugin is opt-in. A site that does not list it gets no stream, no trigger function, no scheduler role and no rule, so
  every other site is unchanged by the release. The window defaults to 300 seconds, the lifetime of the page at the edge,
  because a page cannot be fresher than that anyway; an interval rule and edge purging are off unless the site asks.

  Scenario: A vote that changes a Reference's curation status schedules one snapshot at the end of the debounce window
    Given a trigger function with a 300 second debounce window
    When a Reference is accepted
    Then one home-page snapshot run is scheduled for 300 seconds later
    And the schedule runs the home-page-snapshot task once and deletes itself afterwards

  Scenario: Ten accepts inside one window schedule exactly one snapshot
    Given a trigger function with a 300 second debounce window
    When ten References are accepted over the next 200 seconds
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: A change after the window closes schedules the next snapshot
    Given a trigger function with a 300 second debounce window
    When a Reference is accepted
    And another Reference is accepted 301 seconds later
    Then 2 home-page snapshot runs are scheduled

  Scenario: Posting a Message schedules one snapshot at the end of the debounce window
    Given a trigger function with a 300 second debounce window
    When a Message is posted
    And another Message is posted 100 seconds later
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: A forum post waits a few seconds, not the Reference window
    Given a trigger function with a 300 second debounce window and a 3 second thread window
    When a Message is posted
    And a Message is posted 2 seconds later
    Then one home-page snapshot run is scheduled for 3 seconds later

  Scenario: An open Reference window does not hold a Message back
    Given a trigger function with a 300 second debounce window and a 3 second thread window
    When a Reference is accepted
    And a Message is posted 10 seconds later
    Then 2 home-page snapshot runs are scheduled
    And a home-page snapshot run is scheduled for 300 seconds after the start
    And a home-page snapshot run is scheduled for 13 seconds after the start

  Scenario: A Reference change keeps the long window even when threads have a short one
    Given a trigger function with a 300 second debounce window and a 3 second thread window
    When a Reference is accepted
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: Deleting or editing a Message schedules a snapshot, and a Message change no thread shows does not
    Given a trigger function with a 300 second debounce window
    When a Message changes only a private field
    Then no home-page snapshot run is scheduled
    When a Message is soft-deleted
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: Rating a Reference schedules one snapshot, because a rating changes the order of the pages
    Given a trigger function with a 300 second debounce window
    When a Reference is rated
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: Changing nothing but the number of stars on an accepted Reference schedules one snapshot, because its tile prints the count
    Given a trigger function with a 300 second debounce window
    When an accepted Reference changes from 5 stars to 3 and nothing else
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: Changing only who rated a Reference, or when, schedules nothing
    Given a trigger function with a 300 second debounce window
    When a Reference changes only who rated it
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed

  Scenario: An edit that changes no public field schedules nothing
    Given a trigger function with a 300 second debounce window
    When a Reference changes only a private field
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed

  Scenario: A monitor delivering a Reference nobody has predicted schedules nothing
    A new pending Reference can be recommended only after the Cyclotron has decided it, and the decision is written onto the Reference as a change
    of its own. Until then no page can show it, so the delivery that created it must not run the snapshot.
    Given a trigger function with a 300 second debounce window
    When a pending Reference is delivered that nobody has predicted
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed

  Scenario: The first prediction of a pending Reference schedules a snapshot because the Reference may now be recommended
    Given a trigger function with a 300 second debounce window
    When the Cyclotron's first prediction is written onto a pending Reference
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: A decision time and a sort key are not a prediction
    Every Reference gets a prediction sort key when it is created (0.5 for an unpredicted one, because the index needs a key), and a decision time travels
    with the prediction. Ryan, 2026-11-05: an unpredicted Reference is not 50% and shows nothing, so only the probability itself is a prediction.
    Given a trigger function with a 300 second debounce window
    When a decision time and a sort key are written onto a pending Reference without a probability
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed

  Scenario: The picture of a video on a Reference nobody has predicted schedules nothing, and its first prediction does
    A pending video nobody has predicted is on no page, so its picture has nothing to update. When the Cyclotron's first prediction arrives the run reads
    the Reference again, picture included, so the card appears complete.
    Given a trigger function with a 300 second debounce window
    When the picture of a video is stored on a pending Reference nobody has predicted
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed
    When the Cyclotron's first prediction is written onto that Reference
    Then one home-page snapshot run is scheduled for 300 seconds later

  Scenario: Editing a Reference no page can show schedules nothing, whatever the field
    Given a trigger function with a 300 second debounce window
    When an unpredicted pending Reference is retitled and rated
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed

  Scenario: The run is told which Reference rows changed
    Each change adds the id of its Reference to a list that the run reads, so the run reads again those rows and no others.
    Ten changes to three References in one window list those three.
    Given a trigger function with a 300 second debounce window
    When ten changes arrive for three different References
    Then one home-page snapshot run is scheduled for 300 seconds later
    And the run's list holds exactly those 3 Reference ids

  Scenario: A window with more changes than a list can hold asks for one full read
    A mass import can change more rows than one DynamoDB item can list. The trigger then raises a flag, and that one run reads the corpus.
    Given a trigger function with a 300 second debounce window
    When 2001 References are accepted in one batch
    Then the full-read flag is raised once

  Scenario: A failed schedule creation releases the slot so the next change can try again
    Given a trigger function with a 300 second debounce window
    When a Reference is accepted and creating the schedule fails
    Then the debounce slot is open again
    When another Reference is accepted
    Then one home-page snapshot run is scheduled for 300 seconds after that

  Scenario: Sites that share an account never share a debounce slot
    Given two sites whose trigger functions share one lock table
    When a Reference is accepted on each site
    Then each site has its own home-page snapshot run scheduled

  Scenario: The snapshot re-renders only the pages that read the changed selection
    Given a site with pages that place a references include and a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    And a Reference is accepted and the home-page-snapshot task runs again
    Then only pages that read the file are re-rendered
    And the page "front/index.html" was re-rendered
    And the page "quiet/index.html" was not re-rendered

  Scenario: A site with purge off relies on the edge lifetime
    Given a site with a homePage setting whose purge is off and an edge to invalidate
    When the home-page-snapshot task runs
    Then the task purged no key

  Scenario: A site with purge on invalidates exactly the file it rewrote
    Given a site with a homePage setting whose purge is on and an edge to invalidate
    When the home-page-snapshot task runs
    Then the task purged exactly the snapshot file it wrote

  Scenario: Purge is off unless a site turns it on
    When a site asks for the home-page plugin without naming a purge setting
    Then purge is off and the debounce window is 300 seconds

  Scenario: A site that does not ask for the plugin gets no stream, trigger function, scheduler or rule
    When a site synthesizes its backend without the home-page plugin
    Then no stack changes, no stack is added and no output is added
    And the Reference table is left as it was

  Scenario: A site that asks for the plugin gets the stream, the trigger and the scheduler role and nothing more
    When a site synthesizes its backend with the home-page plugin
    Then the Reference table streams old and new images to one trigger function
    And the trigger function may create only schedules named for the home-page snapshot and pass only the scheduler role
    And the debounce window reaches the trigger function

  Scenario: A site with threads enabled streams its Messages to the same trigger and reuses a stream that already exists
    When a site synthesizes its backend with the home-page plugin and threads enabled
    Then the Message table feeds the same trigger function through its own filter
    And a Message stream that already exists is reused and not replaced

  Scenario: A site with an interval set runs the snapshot on that interval even without changes
    When a site asks for the home-page plugin with an interval of 6 hours
    Then one rule runs the home-page-snapshot task every 6 hours without retries
    And a site that sets no interval gets no rule

  Scenario: The plugin needs a publication and a homePage setting
    When a site asks for the home-page plugin without a publication or without a homePage setting
    Then the backend refuses to synthesize and says what is missing
