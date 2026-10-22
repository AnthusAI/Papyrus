Feature: Every week's knowledge snapshot is archived with cluster identity
  Cluster history cannot be rebuilt after the fact, so each weekly knowledge run
  stores an immutable archive entry for its ISO week as published data next to the
  snapshot, under _data/knowledge/history/. An entry holds the snapshot, every
  cluster of the run with how it relates to the previous run (new, continued with
  its predecessor, merged with its sources, split with its source), the topic and
  entity counts, the run id and the time it was taken. A history index lists the
  entries so a trend feature can read them later. The step never deletes a week.

  Background:
    Given a publication with a cluster run "run-a" dated in the week of "2026-10-19"

  Scenario: The first archive entry carries cluster identity, counts and the run
    When the week of "2026-10-19" is archived
    Then the archive holds an entry for "2026-10-19" from run "run-a"
    And the entry counts 2 clusters
    And the cluster "tc-1" is "new"
    And the cluster "tc-2" has identity "continued" from "tc-2"
    And the history index lists "2026-10-19"

  Scenario: A merged cluster names its sources and a split cluster names its source
    Given the run reports "tc-1" as "merged" from "old-b, old-a"
    And the run reports "tc-2" as "split" from "old-c"
    When the week of "2026-10-19" is archived
    Then the cluster "tc-1" has identity "merged" from "old-a, old-b"
    And the cluster "tc-2" has identity "split" from "old-c"

  Scenario: Archiving the same run again changes nothing
    Given the week of "2026-10-19" is archived
    When the week of "2026-10-19" is archived again
    Then the stored archive is unchanged
    And the history index lists "2026-10-19"

  Scenario: Another run of an archived week is refused and the entry stays
    Given the week of "2026-10-19" is archived
    And a later cluster run "run-b" in the same week
    When the week of "2026-10-19" is archived again
    Then the archive step refuses because the entry is immutable
    And the archive holds an entry for "2026-10-19" from run "run-a"

  Scenario: Replacing a week on purpose leaves the other weeks alone
    Given an earlier archived week "2026-10-12"
    And the week of "2026-10-19" is archived
    And a later cluster run "run-b" in the same week
    When the week of "2026-10-19" is archived with replace
    Then the archive holds an entry for "2026-10-19" from run "run-b"
    And the archive still holds an entry for "2026-10-12"
    And the history index lists the weeks "2026-10-12" then "2026-10-19"

  Scenario: A run from another week is not filed under this week
    When the week of "2026-10-26" is archived
    Then the archive step refuses because the run is outside the week
    And the archive store is empty

  Scenario: There is nothing to archive without a cluster run
    Given a publication with no cluster run
    When the week of "2026-10-19" is archived
    Then the archive step refuses because there is no cluster run
    And the archive store is empty
