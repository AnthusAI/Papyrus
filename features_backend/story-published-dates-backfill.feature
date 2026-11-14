Feature: The backfill moves Stories published before the change to the new dates, and invents nothing
  Before the change every publish stamped the publish time of the version it published and overwrote the version's own record. `papyrus stories
  backfill-published-dates` reads each published Story's versions and derives what they recorded: the earliest recorded publish is the Story's first
  publication, and the published time the Story had is the time its served version went live. It is a dry run unless told to apply, writes only rows that
  differ, keeps every row's own "last changed" time so no card moves in a work queue, and writes nothing the second time. A Story whose first publication
  cannot be derived is listed for a person and its published time is left as it is.

  Scenario: A republished Story gets its first publication back
    Given a Story whose versions recorded publishes on 4 November and 11 November 2026, now showing 11 November as published
    When an operator runs the published dates backfill with --apply
    Then the Story's published time is 4 November 2026
    And its served version's published time is 11 November 2026
    And the served version's publisher is the person the publish recorded

  Scenario: A dry run writes nothing
    Given a Story whose versions recorded publishes on 4 November and 11 November 2026, now showing 11 November as published
    When an operator runs the published dates backfill without --apply
    Then no row of the Story was written
    And the report says what it would write

  Scenario: Running it again writes nothing
    Given a Story whose versions recorded publishes on 4 November and 11 November 2026, now showing 11 November as published
    And an operator has run the published dates backfill with --apply
    When an operator runs the published dates backfill with --apply
    Then no row of the Story was written

  Scenario: Rows keep their own last changed time
    Given a Story whose versions recorded publishes on 4 November and 11 November 2026, now showing 11 November as published
    When an operator runs the published dates backfill with --apply
    Then every version row written still carries its own last changed time

  Scenario: An imported Story keeps its earlier front matter date
    Given a Story imported with the date 1 January 2026 whose only recorded publish was 2 November 2026
    When an operator runs the published dates backfill with --apply
    Then the Story's published time is 1 January 2026

  Scenario: A Story that was taken down once is left for a person
    Given a Story with a version that was taken down and a later version published on 8 November 2026
    When an operator runs the published dates backfill with --apply
    Then the report lists the Story as unclear because a take-down overwrote a publish time
    And the Story's published time is not changed

  Scenario: A Story with no recorded publish is left for a person
    Given a Story that shows as published but whose versions recorded no publish
    When an operator runs the published dates backfill with --apply
    Then the report lists the Story as unclear because no version recorded a publish
    And the Story's published time is not changed
