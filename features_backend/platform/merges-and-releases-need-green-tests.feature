Feature: A red change cannot be merged to the release branches or published as a package
  Agents merge their own pull requests, so nothing but the automatic checks stands between a broken change and the packages every site pins.
  The repository ruleset requires a pull request with the checks ts and python passing before anything reaches main or develop, and the
  release workflow runs the whole test suite on the commit it is about to publish, not only the package smoke test. Nobody is asked to
  approve anything: a green change merges by itself and a red one waits for a fix.

  Scenario: The release job waits for the full test suite as well as the package smoke test
    Given the release workflow
    When its release job is read
    Then it needs the jobs smoke and tests
    And the tests job calls the test workflow tests.yml

  Scenario: The test suite called by a release does not cancel the one started by the push
    Given the test workflow tests.yml
    When its concurrency group is read
    Then the group includes the name of the calling workflow

  Scenario: The branch ruleset requires a pull request and the two test checks without asking a person
    Given the branch ruleset the protect-branches script would create
    When its rules are read
    Then main and develop are covered
    And the required checks are ts and python
    And a pull request is required with no approving reviews
    And force pushes and deletion are refused
    And only the GitHub Actions app may bypass it

  Scenario: A pull request that changes only the board still gets the checks the ruleset requires
    Given the workflow tests-board-only.yml
    When its jobs are read
    Then it reports checks named ts and python
    And it runs them only for pull requests whose every changed file is under project
