Feature: A backend deploy brings every stored deck to the dek of its Story
  Stories saved before the deck column was derived from `dek` can carry an older deck, on the Item row and on the published row that copies it.
  The deploy re-derives the column from each row's own front matter, only where it differs, once per site, before anything renders. It writes only
  the derived column, never front matter. `papyrus stories decks` is the same code run by hand, and its dry run is the health check.

  Background:
    Given a site whose Story and its published row still carry an older deck than the dek in their front matter

  Scenario: The deploy step corrects the Item and the published row and leaves a marker
    When the deck deploy step runs
    Then the Item deck and the published deck are "Current dek."
    And only the deck column of two rows was written
    And the front matter and the update time of the Item are unchanged
    And the site holds the deck migration marker

  Scenario: A second deploy reads one marker and writes nothing
    Given the deck deploy step ran once
    When the deck deploy step runs
    Then no deck row was written

  Scenario: The command reports what it read, what it would write and what was already right
    When the deck repair is run as a dry run, as "papyrus stories decks --dry-run" does
    Then no deck was changed
    And the report counts rows read, rows to write and rows already right for the Items and the published rows

  Scenario: Running the command by hand twice writes nothing the second time
    When the deck repair is run, as "papyrus stories decks" does
    And the deck repair is run, as "papyrus stories decks" does
    Then the second run wrote no row

  Scenario: Rows with no front matter are left alone
    Given the site also has a checklist step with no front matter
    When the deck repair is run, as "papyrus stories decks" does
    Then the checklist step was not written
