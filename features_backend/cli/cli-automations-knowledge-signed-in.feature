Feature: Automations and knowledge queries from the command line without an AWS login
  An editor or admin who has signed in with `papyrus login` can list, show and run automations, read a run
  history and query the knowledge graph without any AWS credentials on the machine. The commands ask the
  site's own signed-in API, which does the table reads and starts the run with the site's own role. A person
  or scheduled job that deliberately uses the AWS lane (PAPYRUS_GRAPHQL_AUTH=iam) is not changed. What the
  site cannot do for a signed-in person, a dry run of Run now and a run history longer than the site
  returns, is refused in one line that says so.

  Scenario: Listing automations uses the editor's sign-in token and no AWS library
    Given a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library
    When the editor runs the signed-in command "papyrus automations list"
    Then the command succeeds and prints the automation
    And the request carried the editor's sign-in token and no AWS signature
    And no AWS library was loaded

  Scenario: The run history is read from the site
    Given a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library
    When the editor runs the signed-in command "papyrus automations runs --id distinctive.ttab"
    Then the command succeeds and prints the automation's runs and their cost line

  Scenario: Run now is asked of the site, with the input the editor gave
    Given a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library
    And the site starts any run it is asked for
    When the editor runs the signed-in command "papyrus automations run --id distinctive.ttab --input '{"proceeding": "1"}'"
    Then the command succeeds and says the run started
    And the site was asked to run "distinctive.ttab" with that input

  Scenario: A dry run of Run now is refused because the site has no dry run
    Given a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library
    When the editor runs the signed-in command "papyrus automations run --id distinctive.ttab --dry-run"
    Then the command fails with a single line saying a dry run is not available when signed in
    And nothing was sent to the site

  Scenario: A longer run history than the site returns is refused
    Given a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library
    When the editor runs the signed-in command "papyrus automations runs --id distinctive.ttab --limit 500"
    Then the command fails with a single line saying that history length is not available when signed in
    And nothing was sent to the site

  Scenario: A user who is not an editor or admin is refused
    Given a signed-in user whom the site does not allow to read automations
    When the editor runs the signed-in command "papyrus automations list"
    Then the command fails with a single line saying automations are for editors and admins

  Scenario: A knowledge query runs on the signed-in session
    Given a signed-in editor of a site with one automation, on a machine with no AWS credentials and no AWS library
    When the editor runs the signed-in command "papyrus knowledge query --query 'a synthetic topic'"
    Then the command succeeds and prints the context the site returned
    And the knowledge request carried the editor's sign-in token and no AWS signature
    And no AWS library was loaded

  Scenario: A knowledge query signed out refuses and does not try AWS
    Given an editor who has chosen the signed-in lane but has not signed in
    When the editor runs the signed-in command "papyrus knowledge query --query 'a synthetic topic' --execution remote"
    Then the command fails with a single line telling them to run "papyrus login"
    And nothing was sent to the site

  Scenario: A job on its own role still signs the knowledge query with IAM
    Given a scheduled job whose role holds AWS credentials and has chosen the IAM lane
    When the job asks for a remote knowledge query
    Then the request is signed with the job's AWS credentials
