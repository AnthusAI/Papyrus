@brand-agnostic @board-story-types-fixtures
Feature: The Stories board lists stories, not every kind of Item
  A story is an Item of a story type. The story type is its own attribute, separate from the section it sits in: today the only story
  type is an article, and posts will be added to the same single list. Wiki pages, doctrine and pages are Items too, and they stay
  reachable in Concepts, the wiki and Sections, but they are never cards on the Stories board and never part of a story count. The
  board asks for story types in the query itself. Because a filtered index query can return a short or empty page that still has more
  behind it, a column keeps reading until it has its page of stories. These scenarios use synthetic Items and never touch production.

  Scenario: A wiki page in Copywriting is not shown, and an article there is
    Given a Copywriting column holding a wiki page and an article
    When the Stories board is built
    Then the article is a card in Copywriting
    And the wiki page is not on the board

  Scenario: A published wiki page is not a Published story
    Given published Items that are a wiki page, a doctrine page, a page and an article
    When the Stories board is built
    Then only the article is in the Published column

  Scenario: Counts include stories only
    Given forty wiki pages, a doctrine page, three articles in Copywriting and one published article
    When the Stories board is built
    Then the board counts four records, three in Copywriting and one in Published

  Scenario: A column of articles loads past a long run of wiki pages
    Given a stage with 1,362 newer wiki pages ahead of 25 articles
    When a column asks for its first page of stories
    Then all 25 articles load even though the first requests came back with no stories
    And every row of the stage was read once and the column then ends
    And a short page that still has a next token is never taken for the end of the column
    And a stage with no stories at all ends without looping

  Scenario: The story types are defined in one place
    Given the story type list
    When the board and its queries need to know what a story is
    Then an article is the only story type until posts are added to that one list
    And wiki pages, doctrine and pages are not stories
