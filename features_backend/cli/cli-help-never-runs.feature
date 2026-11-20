@cli
Feature: Asking any command for help never runs it
  An operator who types a command followed by --help (or -h) wants to read how to use it. Most commands that change
  data write by default, so a help request that reached one would perform the write. Every command, subcommand and
  group therefore answers a help request with its usage and a success exit, before the CLI signs in, builds a backend
  client, or reads or writes anything. Groups list their commands. A word the CLI does not know is still reported as
  unsupported, with the group's usage. Nothing here touches a real site, network, keychain or file.

  Scenario: A command that writes by default only prints its usage
    Given a world where touching a backend client, the network or a file fails the test
    When the operator runs "papyrus references backfill-feed-keys --help"
    Then the exit code is 0
    And the output starts with "Usage: papyrus references backfill-feed-keys"
    And nothing was touched

  Scenario: Help after other arguments is still help
    Given a world where touching a backend client, the network or a file fails the test
    When the operator runs "papyrus ops content list articles --limit 5 -h"
    Then the exit code is 0
    And the output starts with "Usage: papyrus ops content list"
    And nothing was touched

  Scenario: A nested group lists its commands
    Given a world where touching a backend client, the network or a file fails the test
    When the operator runs "papyrus ops content --help"
    Then the exit code is 0
    And the output lists the commands "list", "publish" and "unpublish"
    And nothing was touched

  Scenario: Every route the CLI knows answers help without being run
    Given a world where touching a backend client, the network or a file fails the test
    When the operator asks every route for "--help"
    Then every route exits 0 and prints usage
    And nothing was touched

  Scenario: An unknown command is still reported, with the group's usage
    Given a world where touching a backend client, the network or a file fails the test
    When the operator runs "papyrus references no-such-command --help"
    Then the exit code is not 0
    And the error says the command is unsupported and lists the group's commands
    And nothing was touched
