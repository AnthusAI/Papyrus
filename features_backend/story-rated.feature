@checklist-gate
Feature: Rating is part of publishing
  A site can require that a Story is rated before it publishes, so nothing arrives unrated. "Rate the Story" is a live, required step of the
  Story procedure, and it applies only to a site that turns on the design-system setting publishRequiresRating, which is off unless the site sets
  it. Where it applies, the step is on the Story's checklist, counted in its progress, shown by "papyrus stories next" and by the newsroom panel,
  and checked when a Story publishes. It is closed by evidence, never by hand: the Story has an editor's star rating of 1 to 5 recorded by a
  person, the private rating that "papyrus stories set-stars" sets. A rating of 0 clears it, and a model's prediction is a different record that
  never counts. The step has no exception: a person cannot skip it or mark it not applicable. A new version of a Story keeps its rating, so a
  republish of a rated Story passes. Stories already published stay published whatever their rating; only a publish or republish is gated.

  Scenario: A site that does not turn the setting on is not held to a rating
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    Then the checklist has no item for "rated"
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "rated" showing "not_applicable"
    And the procedure output has no "remaining" line for "rated"

  Scenario: An unrated Story publishes on a site that does not require a rating
    Given a Story at the "copywriting" stage
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: Rated is on the checklist of a site that requires a rating
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story's checklist exists
    Then the checklist item "rated" is "open"
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "rated" showing "not_done"
    And the procedure output has a "remaining" line for "rated"

  Scenario: A person's rating closes the step by itself
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story is rated 4 stars by "Ryan"
    And the Story's checklist exists
    Then the checklist item "rated" is "done"
    And the checklist item "rated" was changed by the system "Automatically, from the editor's star rating"
    And the checklist item "rated" has evidence naming "rated 4 stars by Ryan"

  Scenario: A rating given after the checklist was made closes the step at the next change
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story's checklist exists
    And the Story is rated 5 stars by "Ryan"
    When the checklist is brought up to date after a change
    Then the checklist item "rated" is "done"

  Scenario: An unrated Story is refused and told which command rates it
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And every required step except Rated is closed
    When the Story is published by an editor
    Then publishing was refused saying "Rate the Story (rated)"
    And publishing was refused saying "the Story has no star rating from an editor"
    And publishing was refused saying "papyrus stories set-stars --story story-1 --stars N"

  Scenario: A rating that no person is recorded as giving does not count
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story has a star rating that no person is recorded as giving
    And every required step except Rated is closed
    When the Story is published by an editor
    Then publishing was refused saying "was not recorded by a person"

  Scenario: A rated Story publishes
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story is rated 3 stars by "Ryan"
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded
    And the checklist item "rated" is "done"

  Scenario: A rating given after the last checklist update still lets the Story publish
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And every required step except Rated is closed
    And the Story is rated 2 stars by "Ryan"
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: A rating that was cleared after the step was done blocks publishing
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story is rated 4 stars by "Ryan"
    And every required step is closed
    And the Story's rating is cleared
    When the Story is published by an editor
    Then publishing was refused saying "the Story has no star rating from an editor"

  Scenario: The step cannot be marked done by hand
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step rated --state done --note 'Seems fine'"
    Then the procedure command was refused saying "cannot be marked done by hand"
    And the procedure command was refused saying "papyrus stories set-stars --story story-1 --stars N"
    And the checklist item "rated" is "open"

  Scenario: The step cannot be skipped, even by a person
    Given a Story at the "copywriting" stage
    And the site requires a rating before publishing
    And the Story's checklist exists
    When a person marks the step "rated" skipped with the reason "No time"
    Then the procedure command was refused saying "Rated cannot be skipped"
    And the checklist item "rated" is "open"

  Scenario: A republish of a rated Story passes because a new version keeps the rating
    Given a Story at the "published" stage
    And the site requires a rating before publishing
    And the Story is rated 4 stars by "Ryan"
    And the Story's checklist exists
    And a revision of the published Story is saved at the "copywriting" stage
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: A republish of an unrated published Story is refused until it is rated
    Given a Story at the "published" stage
    And the site requires a rating before publishing
    And the Story's checklist exists
    And every required step except Rated is closed
    When the Story is published by an editor
    Then publishing was refused saying "Rate the Story (rated)"

  Scenario: A published Story that is unrated stays published and is not marked as failing
    Given a Story at the "published" stage
    And the site requires a rating before publishing
    And the Story's checklist exists
    When I run "stories next" with "--story story-1"
    Then the checklist has no item for "rated"
    And the procedure output has no "remaining" line for "rated"
