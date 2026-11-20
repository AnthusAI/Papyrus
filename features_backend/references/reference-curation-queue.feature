@backend @reference-curation-queue
Feature: A real curation run picks References and queues one assignment for each
  `papyrus references curate-recent` without `--dry-run` does no curation itself. It picks the References exactly as the preview does
  (reference-curation-preview.feature), queues one curation assignment for each, and reports what it queued. The assignment worker does the curation
  and records each stage on the assignment, so a Reference whose curation fails is visible there and can be run again.

  The run tries no stage and calls no model. It used to preview every stage first, which cost three model calls for each Reference that were thrown
  away before the worker did the same work again, and a Reference whose preview failed was never queued.

  `--dry-run` previews every stage and queues nothing. `--dry-run --pick-only` lists the References a real run would queue and tries nothing.
  `--resume` continues a preview from its manifest, so a real run refuses it.

  Background:
    Given it is "2026-11-20T12:00:00Z" and the publication holds these References
      | reference     | arrived              | status   |
      | this-morning  | 2026-11-20T08:00:00Z | pending  |
      | yesterday     | 2026-11-19T09:00:00Z | accepted |
      | last-week     | 2026-11-13T09:00:00Z | accepted |

  Scenario: A real run queues an assignment for each picked Reference and tries no stage
    When an operator runs curate-recent for real
    Then a curation assignment is queued for "this-morning, yesterday"
    And no curation stage was tried

  Scenario: A Reference whose curation would fail is still queued
    Given the summary of "yesterday" fails with "the source text could not be read"
    When an operator runs curate-recent for real
    Then a curation assignment is queued for "this-morning, yesterday"

  Scenario: A dry run previews every stage and queues nothing
    When an operator runs curate-recent with "--dry-run"
    Then no curation assignment is queued
    And every curation stage was tried for "this-morning, yesterday"

  Scenario: A dry run that only picks tries nothing and queues nothing
    When an operator runs curate-recent with "--dry-run --pick-only"
    Then no curation assignment is queued
    And no curation stage was tried
    And the run lists "this-morning, yesterday" as the References it would queue

  Scenario: A named Reference that cannot be found is reported and the others are queued
    When an operator runs curate-recent with "--reference reference-last-week-v1 --reference reference-no-such-reference-v1"
    Then a curation assignment is queued for "last-week"
    And the run reports that "no-such-reference" could not be picked and exits as degraded

  Scenario: A real run refuses to resume
    When an operator runs curate-recent with "--resume manifest.json"
    Then the curation run is refused with "--resume continues a --dry-run preview. A real run queues assignments and has nothing to resume."
    And no curation assignment is queued

  Scenario: The operator command asks only for the pick when it will queue
    When the operator command builds its request for a real run
    Then the request asks for "--dry-run --pick-only"

  Scenario: The operator command asks for the full preview on a dry run
    When the operator command builds its request for a dry run
    Then the request asks for the preview with "--dry-run" and never "--pick-only"
