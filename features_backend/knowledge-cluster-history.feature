Feature: The knowledge snapshot keeps a weekly history of its clusters
  A site that draws a cluster river, or a panel of what continued, was born, merged or split,
  needs more than the latest week. The knowledge snapshot writes clusters-history.json next to
  clusters.json. For every weekly run it lists each cluster's stable id, label and item count,
  and the lineage events that connect the run to the one before: born, continued, merged_from
  and split_into. Each snapshot carries the previous file's weeks forward and adds its own, so
  it never has to read every old run. Where no history file exists yet, the weekly archive
  entries are the backfill. The file holds no reader id, email or handle, and a projector reads
  it through KnowledgeSource.history(). It belongs to the snapshot task, so the page reconcile
  never calls it an orphan.

  Background:
    Given a publication whose weekly cluster runs are
      | week       | cluster        | event     | from                  |
      | 2026-10-12 | voice          | new       |                       |
      | 2026-10-12 | agents         | new       |                       |
      | 2026-10-12 | code           | new       |                       |
      | 2026-10-19 | voice          | continued | voice                 |
      | 2026-10-19 | tooling        | merged    | agents, code          |
      | 2026-10-19 | evals          | new       |                       |
      | 2026-10-26 | voice-cloning  | split     | voice                 |
      | 2026-10-26 | speech-synthesis | split   | voice                 |
      | 2026-10-26 | tooling        | continued | tooling               |
      | 2026-10-26 | evals          | continued | evals                 |

  Scenario: Three weekly snapshots build one history with a birth, a merge and a split
    When the snapshot is taken for each of the three weeks in order
    Then clusters-history.json lists the weeks "2026-10-12, 2026-10-19, 2026-10-26" oldest first
    And in the week of "2026-10-12" the event "born" applies to "voice, agents, code"
    And in the week of "2026-10-19" the cluster "tooling" is "merged_from" "agents, code"
    And in the week of "2026-10-19" the cluster "evals" is born
    And in the week of "2026-10-26" the cluster "voice" has "split_into" "speech-synthesis, voice-cloning"
    And in the week of "2026-10-26" the cluster "tooling" continued from "tooling"

  Scenario: Every week lists each cluster's stable id, label and item count
    When the snapshot is taken for each of the three weeks in order
    Then in the week of "2026-10-19" the cluster "tooling" is labelled "Name tooling" with 3 items
    And the week of "2026-10-26" lists "evals, speech-synthesis, tooling, voice-cloning"

  Scenario: A snapshot adds its week to the stored file without reading the old runs
    Given the snapshots of the first two weeks were taken
    When the snapshot is taken for the week of "2026-10-26" from only that week's run
    Then clusters-history.json lists the weeks "2026-10-12, 2026-10-19, 2026-10-26" oldest first
    And the first two weeks are exactly as they were stored

  Scenario: Taking the same week's snapshot again replaces that week and nothing else
    Given the snapshots of the first two weeks were taken
    When the snapshot is taken for the week of "2026-10-19" again
    Then clusters-history.json lists the weeks "2026-10-12, 2026-10-19" oldest first

  Scenario: Without a history file the weekly archive is the backfill
    Given the first two weeks were archived and no clusters-history.json was ever written
    When the snapshot is taken for the week of "2026-10-26" from only that week's run
    Then clusters-history.json lists the weeks "2026-10-12, 2026-10-19, 2026-10-26" oldest first
    And in the week of "2026-10-19" the cluster "tooling" is "merged_from" "agents, code"

  Scenario: A projector reads the history through the knowledge source
    Given the snapshots of the first two weeks were taken
    Then the knowledge source reads a history with the weeks "2026-10-12, 2026-10-19"
    And a knowledge source over an empty snapshot reads no history

  Scenario: The history holds no identity data and the reconcile leaves the file alone
    When the snapshot is taken for each of the three weeks in order
    Then clusters-history.json holds no email, reader or handle
    And the page reconcile treats clusters-history.json as owned by the snapshot task
