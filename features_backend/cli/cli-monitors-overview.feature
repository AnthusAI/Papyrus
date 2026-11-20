Feature: Read monitoring state from the command line without an AWS login
  An editor or admin who has signed in with `papyrus login` can read the same monitoring overview and lists the
  newsroom Monitoring page shows. The commands are read-only, use only that signed-in session, and work on a
  machine that has no AWS credentials, no AWS profile and no AWS client library.

  Scenario: The overview is a short readable summary
    Given a signed-in editor on a machine with no AWS credentials and no AWS library
    And the site's monitoring has one feed, one collection run and one item
    When the editor runs "papyrus monitors overview"
    Then the command succeeds and prints the feed, the run and the item
    And the request carried the editor's sign-in token and no AWS signature
    And no AWS library was loaded

  Scenario: The raw response is available as JSON
    Given a signed-in editor on a machine with no AWS credentials and no AWS library
    And the site's monitoring has one feed, one collection run and one item
    When the editor runs "papyrus monitors overview --json"
    Then the command succeeds and prints exactly the response the site sent

  Scenario: One more page of a list continues after a cursor
    Given a signed-in editor on a machine with no AWS credentials and no AWS library
    And the site's monitoring has one older item to page to
    When the editor runs "papyrus monitors page --list items --cursor c-1"
    Then the command succeeds and prints the older item and that the list has ended
    And the request asked for the "items" list after cursor "c-1" for the publication scope

  Scenario: Held email submissions can be listed
    Given a signed-in editor on a machine with no AWS credentials and no AWS library
    And the site's monitoring has one older item to page to
    When the editor runs "papyrus monitors page --list emailSubmissions --held"
    Then the request asked for the held filter on the "emailSubmissions" list

  Scenario: Signed out, the command refuses and does not try AWS
    Given an editor who has not signed in, on a machine with no AWS credentials and no AWS library
    When the editor runs "papyrus monitors overview"
    Then the command fails with a single line telling them to run "papyrus login"
    And nothing was sent to the site

  Scenario: A user who is not an editor or admin is refused
    Given a signed-in user whose account the site does not allow to read monitoring
    When the editor runs "papyrus monitors overview"
    Then the command fails with a single line saying monitoring is for editors and admins

  Scenario: A publication-scope user cannot ask for the whole pipeline
    Given a signed-in editor whom the site refuses the whole pipeline
    When the editor runs "papyrus monitors overview --scope all"
    Then the command fails with a single line saying the whole pipeline is for admins
