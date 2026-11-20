Feature: The roundup inserter chooses what goes in
  A roundup never holds junk. The inserter adds only Stories of the types the list declares, at or above the site's floor, that became eligible since the
  list's last sent issue, once per story group, and it places them in the shared quality order. Everything it refuses is listed as left out with the reason,
  so an editor can steer. No number of days, and no cap on the number of items, is configured anywhere.

  Scenario: Declared types only
    Given a roundup list that declares the article type
    And a published article and a published post
    When the inserter chooses
    Then only the article is in the issue
    And the post is left out as not a type the list carries

  Scenario: Wiki pages are never added
    Given a roundup list that declares the article type
    And a published wiki page in the window
    When the inserter chooses
    Then the issue is empty
    And the wiki page is left out as not a type the list carries

  Scenario: Retired stories
    Given a roundup list that declares the article type
    And a Story retired after it qualified
    When the inserter chooses
    Then the issue is empty
    And the Story is left out as retired

  Scenario: Three-star floor
    Given a roundup list that declares the article type
    And a published article nobody rated
    When the inserter chooses
    Then the issue is empty
    And the article is left out as below the floor

  Scenario: Late rated, older article
    Given a roundup list that declares the article type
    And an article published a month ago and rated three stars today
    When the inserter chooses
    Then the article is in this week's issue
    And the next issue's window starts after the article became eligible, so it is not offered again

  Scenario: Already sent
    Given a roundup list that declares the article type
    And an article that was in last week's issue
    When the inserter chooses
    Then the issue is empty
    And the article is left out as already sent

  Scenario: Duplicate story group
    Given a roundup list that declares the article type
    And two articles of the same story group, the second eligible later
    When the inserter chooses
    Then only the first eligible article is in the issue
    And the other is left out as a duplicate of the first

  Scenario: Excluded by a person
    Given a roundup list that declares the article type
    And an article an editor excluded from this issue
    When the inserter chooses
    Then the issue is empty
    And the article is left out as removed by a person

  Scenario: Quality order inside a slot, and a pin
    Given a roundup list that declares the article type
    And three articles in one section rated five, four and three stars
    When the inserter chooses
    Then they appear in the shared quality order
    When an editor pinned the three-star article to the first place
    And the inserter chooses
    Then the three-star article comes first and the others follow in quality order

  Scenario: A list that declares no types cannot assemble
    Given a roundup list that declares no types
    When the roundup is assembled
    Then it is refused because the list must declare the Story types it carries

  Scenario: The window comes from the cadence
    Given a weekly list that never sent an issue and an article from the week before
    When the roundup is assembled
    Then the window opens at the start of the current period and the older article is not in it
    And no number of days is configured anywhere
