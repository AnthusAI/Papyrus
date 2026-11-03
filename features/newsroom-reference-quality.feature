@brand-agnostic @reference-feed-fixtures
Feature: An editor finds the highest quality References again by their stars, newest first
  Editors rate References one to five stars while they curate, and later need to go back and find the good ones: most often "the most recent,
  highest quality things", where highest sometimes means only five stars, sometimes four or more, sometimes three or more, but never "only
  three" and never "only two". The newsroom References page has a third Sort, Quality, beside Best bets and Newest, and a row labelled Minimum
  stars with Any, 3+, 4+ and 5, each with a star and its number so colour is never the only sign. Quality lists the References with the most
  stars first and the newest first within each number of stars; only starred References are in it. A minimum keeps the References with at least
  that many stars in whichever Sort is chosen. Stars are separate from the vote, so most starred References are voted: choosing Quality or a
  minimum while Show is Unrated moves Show to All, in view, and choosing Show afterwards is honoured. The stars index is by arrival and cannot
  order by prediction: choosing a minimum while Sort is Best bets moves Sort to Newest, and choosing Best bets sets the minimum back to Any.
  Sort, Show and the minimum are remembered in this browser. A Reference that has been replaced by a newer version, or archived, is never shown,
  whatever its stars. While a search is open, Sort reads Relevance, Newest and Quality, opens on Relevance and is not saved, and the minimum is
  the same saved one. These scenarios use synthetic References in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: Quality lists the most stars first and the newest first within each number of stars
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor chooses the Quality sort
    Then the References appear five stars first, newest first among each number of stars, down to one star
    And the unstarred, the archived and the replaced References are not listed
    And every star level of every corpus was read from the stars index

  Scenario: Four or more on Newest merges the five and four star levels by arrival
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor chooses Newest and then the minimum 4+
    Then the five and four star References are listed together, newest arrival first
    And only the five and four star levels were read, and not the feed's own index

  Scenario: Five stars lists only five star References
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor chooses Newest and then the minimum 5
    Then only the five star References are listed, newest first
    And choosing 3+ afterwards adds the four and three star References by arrival

  Scenario: Choosing Quality or a minimum moves Show from Unrated to All, and Show stays the editor's
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor chooses Quality while Show is Unrated
    Then Show reads All in view
    And choosing Unrated afterwards lists the unrated starred References, and choosing Rated lists the rated ones

  Scenario: Best bets sets the minimum back to Any
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor has chosen a minimum of 4+ and then chooses Best bets
    Then the minimum reads Any and the feed lists unstarred References again

  Scenario: A minimum moves Best bets to Newest
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor chooses Best bets, Unrated and then the minimum 3+
    Then Sort reads Newest and Show reads All

  Scenario: A minimum that finds nothing says which minimum and offers a way to clear it
    Given a synthetic site where no Reference has five stars
    When the editor chooses the minimum 5
    Then the page says "Nothing here has 5 stars." with a Show any stars button
    And pressing it sets the minimum to Any and lists the References again

  Scenario: The choices survive a reload
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor chooses Newest and the minimum 4+ and reloads the page
    Then Newest, All and 4+ are chosen again and the same References are listed

  Scenario: Archived and replaced References are never shown, and a page of them does not stop the list
    Given a synthetic site where sixty archived five star References arrived after the live ones
    When the editor chooses the Quality sort
    Then the live References are listed after the page of archived ones is skipped, reading further pages by itself

  Scenario: A search can be ordered Newest or by Quality and narrowed by a minimum
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor searches for a word in every title and chooses Newest, then Quality, then the minimum 4+
    Then Sort reads Relevance, Newest and Quality and opens on Relevance
    And Newest orders the matches by arrival, Quality puts the unstarred matches after the starred ones, and 4+ keeps only four and five stars
    And the search asked for each ordering and minimum, the minimum is the saved one, and the search's own sort is not saved
    And clearing the search brings back the saved Sort, Show and minimum

  Scenario: The new controls have no borders and fit a phone
    Given a synthetic site with References of one to five stars, some unstarred, one archived and one replaced by a newer version
    When the editor looks at the Sort, Show and Minimum stars controls
    Then the Minimum stars row is labelled, each minimum has a star icon and its number except Any, and none has a border
    And nothing scrolls sideways at 375 pixels
