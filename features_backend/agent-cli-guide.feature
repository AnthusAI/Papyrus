@cli
Feature: An agent can use the Papyrus CLI without guessing
  People and AI agents edit a newsroom through the `papyrus` command. They must be able to learn its syntax from the CLI itself:
  `papyrus guide` prints task-first recipes with exact syntax, every command's `--help` prints its real flags, its lane (the
  signed-in editor or the AWS operator) and whether it writes (most commands write unless `--dry-run`, and some have no dry run
  at all), a group lists its commands with one-line descriptions, and a command run with no arguments prints its usage along with
  the error. The guide itself is checked in CI: every command in it must exist and every flag it uses must be in that command's
  usage, so a change to the CLI that is not reflected in the guide fails the build. Nothing here reaches a real site.

  Scenario: The guide lists its tasks and prints one of them
    When an agent runs "papyrus guide --list"
    Then the command succeeded
    And the printed text names the tasks "orientation", "find", "file-reference", "tag-and-link", "write-story", "publish", "checks" and "troubleshooting"
    When an agent runs "papyrus guide file-reference"
    Then the printed text starts with "## File a Reference from URLs"
    And the printed text contains "references create-from-catalog"

  Scenario: A command's help names its flags, its lane and whether it writes
    When an agent runs "papyrus references create-from-catalog --help"
    Then the command succeeded
    And the printed text starts with "Usage: papyrus references create-from-catalog"
    And the printed text contains "--catalog"
    And the printed text contains "--corpus-key"
    And the printed text contains "--dry-run"
    And the printed text contains "Lane:"
    And the printed text contains "Writes: yes, by default"

  Scenario: A command that cannot preview says so
    When an agent runs "papyrus ops relations import-types --help"
    Then the printed text contains "NO --dry-run"

  Scenario: A group lists its commands with a description each
    When an agent runs "papyrus references --help"
    Then the command succeeded
    And the printed text has a line for "make-catalog" followed by its description
    And the printed text says "register" is for the local pod only

  Scenario: A command run with no arguments prints its usage with the error
    When an agent runs "papyrus stories create" with no site and no arguments
    Then the command failed
    And the printed error has the usage of "papyrus stories create" before the error
    And the printed error contains "needs arguments"

  Scenario: Every command in the guide exists and every flag it uses is in its usage
    When the guide's fenced commands are checked against the CLI
    Then every command is a route of the CLI
    And every flag it uses appears in that command's help
    And every recipe for an unmerged pull request is marked pending

  Scenario: Every route prints real help
    When every route is asked for "--help"
    Then each prints usage that begins with "Usage"
    And each command says its lane and whether it writes
