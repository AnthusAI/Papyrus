Feature: The CLI runs as the signed-in person by default and never picks AWS credentials by itself
  `papyrus login <site>` gets a token from the site's own sign-in, and every command then runs as that person: the
  signed-in lane is the default. AWS credentials can do far more than any one task needs, so the operator lane (IAM) is
  used only when a process names it, with `papyrus --auth iam <group> <command>` or PAPYRUS_GRAPHQL_AUTH=iam. Workers,
  scheduled jobs and the deploy and CI steps that run as their own AWS role name it in their own definitions. With no
  sign-in and no lane named, a command stops before it reads or writes anything and says what to do. A CLI newer than the
  site's backend never switches lanes to get round what that backend cannot do.

  Background:
    Given a machine with AWS credentials in its environment and no Papyrus sign-in

  Scenario: With no sign-in and no lane named, a command refuses and names both ways forward
    When a command asks for headers to call the site API
    Then it refuses with a message that names "papyrus login <site>" and "papyrus --auth iam"
    And the refusal exits with status 2
    And nothing was signed with the AWS credentials

  Scenario: A signed-in session is the default lane
    Given a signed-in session for the site
    When a command asks for headers to call the site API
    Then the headers come from the signed-in session
    And nothing was signed with the AWS credentials

  Scenario: A signed-in session that cannot sign is not replaced by AWS credentials
    Given a signed-in session for the site whose sign-in has expired
    When a command asks for headers to call the site API
    Then it refuses with the session's own message to sign in again
    And nothing was signed with the AWS credentials

  Scenario: `papyrus --auth iam` names the operator lane for the whole command
    When the command line starts with "--auth iam"
    And a command asks for headers to call the site API
    Then the request is signed with the AWS credentials

  Scenario: PAPYRUS_GRAPHQL_AUTH=iam names the operator lane the same way
    Given the process names the operator lane with PAPYRUS_GRAPHQL_AUTH=iam
    When a command asks for headers to call the site API
    Then the request is signed with the AWS credentials

  Scenario: The operator lane named with no AWS credentials refuses instead of trying the signed-in lane
    Given a signed-in session for the site
    And the process names the operator lane with PAPYRUS_GRAPHQL_AUTH=iam
    And the AWS credentials have expired
    When a command asks for headers to call the site API
    Then it refuses with a message about AWS credentials
    And the signed-in session was not used

  Scenario: `--auth` and PAPYRUS_GRAPHQL_AUTH naming different lanes is refused
    Given the process names the operator lane with PAPYRUS_GRAPHQL_AUTH=iam
    When the command line starts with "--auth user"
    Then it refuses with a message that says only one of them may speak

  Scenario: An unknown lane is refused
    When the command line starts with "--auth aws"
    Then it refuses with a message that names "papyrus --auth iam"

  Scenario: The leading flags combine in either order and leave the command's own flags alone
    When the command line is "--auth iam --site a.anth.us home-page snapshot --auth user"
    Then the lane is "iam" and the site is "a.anth.us"
    And the command that runs is "home-page snapshot --auth user"

  Scenario: Knowledge query with no sign-in refuses instead of running the local engine
    When a knowledge query runs with execution "auto"
    Then it refuses with a message that names "papyrus login <site>" and "papyrus --auth iam"
    And the local engine did not run

  Scenario: The operator CLI's cloud commands with no sign-in point at login, not at AWS profiles
    When the operator CLI checks that it can reach the site
    Then it refuses with a message that names "papyrus login <site>" and "papyrus --auth iam"
    And the refusal exits with status 2

  Scenario: Every site function that calls the site API names the operator lane next to its endpoint
    Then no function definition sets PAPYRUS_GRAPHQL_ENDPOINT except through the shared site API access
    And the shared site API access names PAPYRUS_GRAPHQL_AUTH iam with every endpoint

  Scenario Outline: Every worker outside the site functions names the operator lane in its own definition
    Then the worker "<worker>" names the operator lane

    Examples:
      | worker                                 |
      | the knowledge run image                |
      | the procedure runner image             |
      | the procedure runner's child processes |
      | the monitoring stack's GraphQL workers |
      | the staging build's drafts export      |
