Feature: A green tests run is reused when the code is identical
  Ryan saw the whole suite run about four times per change: on the pull request into develop, on develop after the merge, on the release pull
  request, and on main before the stack deploy. When an earlier run of the tests workflow passed on a byte-identical git tree, the heavy jobs
  are skipped and the run says which earlier run it relied on. These scenarios are checked by procedures/newsroom/tests/test_reuse_green_tests.py.

  Scenario: The same tree already passed
    Given a successful tests run on develop whose tree is T
    When the release pull request or the push to main is tested on tree T
    Then the ts and python jobs are skipped and the summary links the earlier run

  Scenario: A different tree runs everything
    Given no earlier successful run tested this tree
    Then the full suite runs

  Scenario: A failed run is never reused
    Given the only earlier run on this tree failed or was cancelled
    Then the full suite runs

  Scenario: A lookup problem runs everything
    Given the GitHub API call fails
    Then the full suite runs

  Scenario: Runs from forks are not believed
    Given a green run from a fork's pull request on the same tree
    Then it is ignored, because the fork supplied its own copy of the workflow

  Scenario: Stack deploy keeps its gate
    Given a push to main
    Then the deploy job still needs the tests job, which passes only when the suite passed or a green run on the same tree was reused
