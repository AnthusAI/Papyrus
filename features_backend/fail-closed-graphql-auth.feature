Feature: The CLI never picks AWS credentials by itself
  A person runs Papyrus commands as the signed-in user. AWS credentials grant far more than any task needs, so a command
  that finds no session stops and says how to sign in. Workers that sign as themselves, and break-glass commands, name the
  AWS lane on purpose.

  Background:
    Given a machine with AWS credentials in its environment and no Papyrus sign-in

  Scenario: A command with no session and no opt-in refuses and says to log in
    When a command asks for headers to call the site API
    Then it refuses with one line that says to run "papyrus login"
    And the command would exit with status 2
    And no request was signed with AWS credentials

  Scenario: Naming the IAM lane on purpose signs with AWS credentials
    Given the operator names the IAM lane with PAPYRUS_GRAPHQL_AUTH=iam
    When a command asks for headers to call the site API
    Then the request is signed with the AWS credentials

  Scenario: A session that yields no headers is not replaced by AWS credentials
    Given a sign-in session exists but yields no headers
    When a command asks for headers to call the site API
    Then it refuses with one line that says to run "papyrus login"
    And no request was signed with AWS credentials

  Scenario: Knowledge query with no session does not run the local engine
    When the operator runs a knowledge query with execution "auto"
    Then it refuses with one line that says to run "papyrus login"
    And the local engine did not run

  Scenario: Knowledge query runs the local engine only when asked for it
    When the operator runs a knowledge query with execution "local"
    Then the local engine ran once

  Scenario: Cloud authoring in the operator CLI points at login, not at AWS profiles
    When the operator CLI checks its cloud authoring access
    Then it refuses with one line that says to run "papyrus login"
    And the message does not mention AWS_PROFILE

  Scenario Outline: A worker that signs as itself names the IAM lane
    Then <worker> names PAPYRUS_GRAPHQL_AUTH iam in its image or stack definition

    Examples:
      | worker                              |
      | the knowledge run image             |
      | the procedure runner image          |
      | the monitoring router function      |
      | the scheduled knowledge run tasks   |
      | the newsletter functions            |
      | the content actions function        |
      | the Slack delivery function         |
      | the inbound email processor         |
      | the automation view function        |
      | the editorial checks function       |
