Feature: Curation changes reach the home-page pages by themselves, in one debounced run
  A site that turns on the home-page plugin does not wait for someone to run a command. Every change to a Reference that a
  public page shows or ranks by (its curation status, its place in the feed, its prediction, its version state, its title or
  its section) arrives on the Reference table's DynamoDB stream. A small trigger function turns a burst of such changes into
  one home-page-snapshot run at the end of a quiet window: the first change opens the window and schedules the run, the
  changes that follow inside the window find it open and schedule nothing, because the run reads them all. The run writes the
  snapshot only when it changed and re-renders only the pages that read the changed selection.

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

  Scenario: An edit that changes no public field schedules nothing
    Given a trigger function with a 300 second debounce window
    When a Reference changes only a private field
    Then no home-page snapshot run is scheduled
    And no debounce slot is claimed

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

  Scenario: A site with an interval set runs the snapshot on that interval even without changes
    When a site asks for the home-page plugin with an interval of 6 hours
    Then one rule runs the home-page-snapshot task every 6 hours without retries
    And a site that sets no interval gets no rule

  Scenario: The plugin needs a publication and a homePage setting
    When a site asks for the home-page plugin without a publication or without a homePage setting
    Then the backend refuses to synthesize and says what is missing
