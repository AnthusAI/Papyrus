@brand-agnostic @board-story-types-fixtures
Feature: The Stories board lists stories, not every kind of Item
  A story is an Item of a story type. The story type is its own attribute, separate from the section it sits in. Nothing in the engine lists the story
  types: wiki pages, doctrine and pages are the fixed system set, and every other Item type is a story, so a site's own new type is on the
  board with no engine change. Those Items stay
  reachable in Concepts, the wiki and Sections, but they are never cards on the Stories board and never part of a story count. The
  board asks to leave the system types out in the query itself. Because a filtered index query can return a short or empty page that still has more
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

  Scenario: The system types are defined in one place
    Given the system type list
    When the board and its queries need to know what a story is
    Then wiki pages, doctrine and pages are not stories
    And an article, a post, a newsletter issue, a story with no type and any other type are stories, and the query excludes only the system types

  Scenario: A site's own story type is on the board
    Given Items of the site's own type "guide" and of the types wiki page, post, newsletter issue and untyped
    When the Stories board is built
    Then the guide, the post, the newsletter issue and the untyped story are cards and the wiki page is not

  Scenario: A published Story is not shown in the column it was once written in
    Given a Story written in Copywriting and later published, whose newest version is not in the first page of the Published column
    When the Stories board loads the Copywriting column
    Then the superseded Copywriting version is not loaded and the Story is not a Copywriting card
    And the board asks for story types that are not superseded
