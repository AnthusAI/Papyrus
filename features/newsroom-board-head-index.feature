@brand-agnostic
Feature: The board reads one row per story
  Every saved version of a story keeps the stage it was written in, so the old stage index holds every version, and the board hid the
  superseded ones with a query filter only after DynamoDB had read them: on Machines on Machines the Published column read about five rows
  for every story it showed, and the cost grew with every save. On the head stage index each story has one row, in the stage it is in, so a
  column reads exactly the stories it shows, 25 at a time, and the next 25 only when the editor scrolls to the end of the column.

  A site switches when its backend has the index and `papyrus stories head-index` has filled it (the site's brand sets
  storyHeadStageIndex). Until then, and on a backend that turns out not to have the index, the board reads the old stage index exactly as
  before. These scenarios use synthetic stories and a fake index that counts the rows it reads; they never touch production.

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
    Then it reads 25 rows for its first page, one per story, in one request
    And the old stage index would have read every saved version to fill the same column

  Scenario: A site that has not switched keeps today's board
    Given a site whose brand does not set storyHeadStageIndex
    When the board loads a column
    Then it reads the old stage index and still hides superseded versions
    And a refresh replaces only the rows that changed, as before

  Scenario: A backend without the head stage index falls back for the rest of the session
    Given a site that has switched but whose backend has no head stage index yet
    When the board loads a column
    Then the column still shows its stories, read from the old stage index
    And later columns and refreshes read the old stage index without asking for the missing one again
    But any other error, such as a refused authorization, is shown and not taken for a missing index
