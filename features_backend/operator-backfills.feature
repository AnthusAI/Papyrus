@backend @operator-backfills
Feature: A backfill that only an operator can run says so before it does anything
  The signed-in editor lane reads Reference, Assignment and KnowledgeImportRun records but cannot change them; only the operator lane (AWS
  credentials, PAPYRUS_GRAPHQL_AUTH=iam) can. A backfill used to read everything, print a preview that gave no warning, and then fail on the
  first write with "Not Authorized to access updateReference". Now each of them names itself an operator command and the operator lane
  before it reads anything. A write on the signed-in lane is refused with nothing changed, and a preview prints one notice first so it is
  not read as a promise that the write will work. On the operator lane nothing changes. Editor permissions are not widened. Nothing here
  touches a live site: the backend is in memory.

  Scenario Outline: A write on the signed-in lane is refused before any work
    Given the command line is signed in as an editor
    When "<command>" is run to write
    Then it stops with a message that it is an operator command
    And the message names the operator lane
    And it says nothing was changed
    And no backend client was opened
    Examples:
      | command                                      |
      | references backfill-medium                   |
      | references backfill-public-fields            |
      | references backfill-feed-keys                |
      | references backfill-reviewed-feed-key        |
      | references backfill-corpus-storage-paths     |
      | sections backfill-feed-fields                |
      | sections backfill-operational-indexes        |

  Scenario: A preview on the signed-in lane warns first
    The medium backfill previews by default, so the warning comes before the mode line.
    Given the command line is signed in as an editor
    When "references backfill-medium" is run as a preview
    Then the first line it prints is an operator-lane notice
    And the notice says the preview only reads

  Scenario Outline: The operator lane is not affected
    Given the command line uses the operator lane
    When "<command>" is run to write
    Then no operator-lane message is printed
    And the backend client was opened
    Examples:
      | command                    |
      | references backfill-medium |
      | references backfill-public-fields |
      | references backfill-feed-keys |
