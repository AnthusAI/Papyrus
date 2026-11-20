@backend @reference-curation-preview
Feature: The curation preview picks References and tries each curation stage in order
  `papyrus references curate-recent --dry-run` previews a curation run over the References a publication took in lately. It picks the References, then
  for each one it tries the four stages of curation in a fixed order (find the identifier, resolve the title and subtitle, write the summary, assess
  the source quality) without saving anything. A real run does none of this work itself: it queues an assignment for each Reference
  (reference-curation-queue.feature).

  By default the preview picks every Reference that arrived in the last 48 hours, whatever its curation status, newest first. `--since` moves the start
  of the window, `--all` drops the window, `--max-count` keeps only the newest few, and `--reference` names References outright and ignores the window.

  The identifier comes first because the later stages depend on it: when it cannot be worked out, the other three stages are skipped and say why. After
  that each stage stands alone, so a failed summary does not stop the quality assessment. One Reference failing never stops the next Reference, but it
  does make the whole run report that it is degraded.

  A preview writes a manifest of what each stage did. Run again with `--resume` and that manifest, it tries only the stages that did not succeed.

  Background:
    Given it is "2026-11-20T12:00:00Z" and the publication holds these References
      | reference     | arrived              | status   |
      | this-morning  | 2026-11-20T08:00:00Z | pending  |
      | yesterday     | 2026-11-19T09:00:00Z | accepted |
      | last-week     | 2026-11-13T09:00:00Z | accepted |
      | never-dated   |                      | accepted |

  Scenario: The last 48 hours are picked by default, whatever the curation status
    When the curation preview runs
    Then the preview picks "this-morning, yesterday" in that order
    And the run is not degraded

  Scenario: A later start of the window picks fewer References
    When the curation preview runs for everything since "2026-11-20T00:00:00Z"
    Then the preview picks "this-morning" in that order

  Scenario: A start of the window that is not a time is refused
    When the curation preview runs for everything since "last tuesday"
    Then the curation preview is refused with "Invalid --since value: last tuesday"

  Scenario: Asking for everything includes old References and References with no date
    When the curation preview runs for every Reference
    Then the preview picks all 4 References

  Scenario: A maximum count keeps the newest References
    When the curation preview runs for every Reference with a maximum of 1
    Then the preview picks "this-morning" in that order

  Scenario: A Reference named outright is picked even when it is outside the window
    When the curation preview runs for the Reference "last-week"
    Then the preview picks "last-week" in that order

  Scenario: A named Reference that cannot be found is reported and the others are still previewed
    When the curation preview runs for the References "last-week, no-such-reference"
    Then the preview picks "last-week" in that order
    And the preview reports that "no-such-reference" could not be picked
    And the run is degraded

  Scenario: The stages are tried in a fixed order
    When the curation preview runs for the Reference "yesterday"
    Then the stages tried for "yesterday" are "identifier, title and subtitle, summary, quality" in that order
    And nothing was saved by any stage

  Scenario: Without an identifier the other stages are skipped
    Given the identifier of "yesterday" cannot be worked out
    When the curation preview runs for the Reference "yesterday"
    Then the stages tried for "yesterday" are "identifier" in that order
    And the title and subtitle, summary and quality stages of "yesterday" are skipped because "identifier prepass failed"
    And the Reference "yesterday" is reported as failed

  Scenario: A Reference with no identifier to find carries on to the other stages
    Given "yesterday" has no identifier to find
    When the curation preview runs for the Reference "yesterday"
    Then the stages tried for "yesterday" are "identifier, title and subtitle, summary, quality" in that order
    And the run is not degraded

  Scenario: A failed stage does not stop the stages after it
    Given the summary of "yesterday" fails with "the source text could not be read"
    When the curation preview runs for the Reference "yesterday"
    Then the stages tried for "yesterday" are "identifier, title and subtitle, summary, quality" in that order
    And the Reference "yesterday" is reported as failed because "the source text could not be read"

  Scenario: One failed Reference does not stop the next
    Given the summary of "this-morning" fails with "the source text could not be read"
    When the curation preview runs
    Then the Reference "this-morning" is reported as failed because "the source text could not be read"
    And the Reference "yesterday" is reported as fine
    And the run counts 1 succeeded and 1 failed
    And the run is degraded

  Scenario: A resumed run tries only the stages that did not succeed
    Given the summary of "yesterday" fails with "the source text could not be read"
    And the curation preview has run for the Reference "yesterday"
    And the summary of "yesterday" works again
    When the curation preview is resumed from its manifest
    Then the stages tried for "yesterday" in the resumed run are "summary" in that order
    And the run is not degraded

  Scenario: Parallel work is not done yet and the run says so
    When the curation preview runs with 4 References at a time
    Then the run warns "max_parallel=4 requested; deterministic sequential execution is used in v1."
