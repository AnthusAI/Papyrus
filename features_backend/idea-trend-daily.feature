Feature: Cited Trends can run daily or on demand
  Cited Trends drafts stories from the knowledge snapshot that the cloud run has just published. While an editor iterates on the
  trend path, a weekly cadence is too slow, so the step has to draft after a scheduled run, a daily run or a run someone starts by
  hand, and it still has to refuse a snapshot that is not this run's. The knowledge snapshot is weekly and the snapshot stage stamps
  it with the Monday of the run's week, so on any other day of the week the snapshot is fresh when it carries that Monday, the
  run's own date, or a date at most one day older (the age is configuration). A snapshot of an earlier week is skipped, whatever day
  the run starts. The trend window is whole weeks in days: the last 28 days against the 28 before them unless a site asks for
  fewer, so a daily cadence can use a shorter window later without changing the default.

  Scenario Outline: A scheduled, daily or manual run drafts from its own snapshot
    Given the run started at "<started>"
    And the published snapshot says it is as of "<as of>"
    When the trend-drafts step runs
    Then the step drafts from the snapshot as of "<as of>"

    Examples:
      | started              | as of      |
      | 2026-10-26T05:00:12Z | 2026-10-26 |
      | 2026-10-28T10:00:00Z | 2026-10-26 |
      | 2026-10-28T10:00:00Z | 2026-10-28 |
      | 2026-10-28T10:00:00Z | 2026-10-27 |
      | 2026-11-01T22:00:00Z | 2026-10-26 |

  Scenario Outline: A snapshot that is not this run's is skipped
    Given the run started at "<started>"
    And the published snapshot says it is as of "<as of>"
    When the trend-drafts step runs
    Then the step is skipped as stale and files nothing

    Examples:
      | started              | as of      |
      | 2026-10-28T10:00:00Z | 2026-10-19 |
      | 2026-10-28T10:00:00Z | 2026-10-29 |
      | 2026-10-26T05:00:00Z | 2026-10-24 |

  Scenario: The allowed age of the snapshot is configuration
    Given the run started at "2026-10-26T05:00:00Z"
    And the published snapshot says it is as of "2026-10-24"
    And the allowed snapshot age is 2 days
    When the trend-drafts step runs
    Then the step drafts from the snapshot as of "2026-10-24"

  Scenario: The trend window is 28 days against the 28 before unless it is configured
    Given the run started at "2026-10-26T05:00:12Z"
    And the published snapshot says it is as of "2026-10-26"
    When the trend-drafts step runs
    Then the command uses the default trend window
    When the trend window is set to 14 days and the trend-drafts step runs
    Then the command uses a trend window of 14 days

  Scenario: A shorter window compares the last weeks with the same number of weeks before them
    Given the knowledge snapshot of a week in which a licence, a task and a platform carry the biggest counts
    When the trend window is 14 days
    Then NVIDIA is counted with 5 mentions against 1 before

  Scenario: A window that is not whole weeks of the snapshot is refused
    When the trend window is 10 days
    Then the operator is told the window must be 7, 14, 21 or 28 days
