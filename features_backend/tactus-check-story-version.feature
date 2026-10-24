@backend @editorial-checks
Feature: A Tactus procedure checks a story version
  A copy-edit procedure is a bot in the newsroom. It reads a story version, asks
  Papyrus to run the editorial checks on that exact version, and gets back the
  findings with the pack version and a plain clean flag. It fixes what the
  checks found, saves the fix as the next version, and checks again, so it can
  stop when the new version is clean. The checks are the same ones editors see
  in the console: the publication's policies, run by the site's editorial
  checks function, with the result stored with the version.

  Background:
    Given a site with a story whose first draft reads "This game-changing release ships today."
    And the publication has an enabled policy "no-hype" that flags "game-changing"

  Scenario: A copy-edit procedure checks a version, fixes the findings, and re-checks until it is clean
    When the procedure checks the story's first version
    Then the check status is "checked" and the version is not clean
    And there is 1 finding for rule "no-hype" quoting "game-changing"
    And the result names version 1 and the policy pack version that was used
    When the procedure saves a fixed version reading "This release ships today."
    And the procedure checks the story's newest version
    Then the check status is "checked" and the version is clean
    And the result names version 2 and there are no findings
    And the first version still has its stored findings

  Scenario: A finding that quotes nothing is about the whole document
    Given the stored check also holds a review finding for rule "general-meaning-first" that quotes nothing
    When the procedure checks the story's first version
    Then the check status is "checked" and the version is not clean
    And the finding for rule "general-meaning-first" is marked as about the whole document
    And the finding for rule "no-hype" is marked as a quote finding

  Scenario: Checking is skipped when the publication turned editorial checks off
    Given the publication turned editorial checks off
    When the procedure checks the story's first version
    Then the check status is "skipped" and the version is not clean

  Scenario: The procedure cannot check a version that does not exist
    When the procedure checks the version "no-such-version"
    Then the check is refused as "Story version not found"
