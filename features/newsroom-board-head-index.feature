@wip @brand-agnostic
Feature: The board reads one row per story
  Pending until the console reads the head stage index (PPY-52f3da, step 5 of docs/plans/story-head-stage-index.md), which waits for the
  backfill on each site. Today the board's stage columns read the old stage index, which holds every saved version, and hide superseded
  rows with a query filter after DynamoDB has read them. On the head stage index each story has one row, in the stage it is in, so a
  column reads exactly the stories it shows. These scenarios use synthetic stories and never touch production.

  Scenario: A published story that was once in Copywriting shows only in Published
    Given a story that was written in Copywriting and then published in a later version
    When the board loads its columns from the head stage index
    Then the story shows in Published only
    And the Copywriting column read no row of that story

  Scenario: A refresh after a new version replaces the card wherever it was
    Given a board showing a story in Copywriting
    When an editor saves a new version of that story in Illustration and the board refreshes
    Then the story shows once, in Illustration
    And no card of that story is left in Copywriting

  Scenario: A column reads only the stories it shows
    Given 30 stories in Published, each published five times
    When the board loads the Published column
    Then it reads 25 rows for its first page, one per story
