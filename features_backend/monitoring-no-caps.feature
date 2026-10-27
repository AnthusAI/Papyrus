Feature: Monitors have no arbitrary limits; only time, rate limits and row size bound them
  A monitor reads everything its source has that it has not collected yet, and parks every item that waits
  for a classifier. Nothing is cut at an invented number. What does bound the work is real: the Lambda's time
  (the rest is read by the next pass), a source's rate limit (its Retry-After is honoured) and the size of a
  DynamoDB row (so each parked item is a row of its own).

  Scenario: More than 25 parked items all survive and are decided when the classifier is ready
    Given a router for a publication whose classifier is not ready
    And forty stories were collected while it waited
    Then all forty stories are parked, each in a row of its own
    When the classifier becomes ready and the router runs again
    Then every one of the forty stories is decided for that publication
    And the publication's park is removed

  Scenario: A park written before parked items had rows keeps every item it listed
    Given a router for a publication whose classifier is not ready
    And three stories were collected while it waited
    And the publication's park is stored the old way, with its three items in one list
    When the router runs again
    Then the park header no longer carries a list
    And the three items are parked in rows of their own

  Scenario: A collector pass with many new decisions reads them all
    Given a TTAB monitor and a Reading Room that holds two hundred and fifty new decisions
    When the monitor collects
    Then all two hundred and fifty decisions are recorded
    And the monitor asked for every page until the search ran out

  Scenario: A later pass stops at the decisions it already has
    Given a TTAB monitor that has collected two hundred and fifty decisions
    And the Reading Room has thirty newer decisions
    When the monitor collects a day later
    Then only the thirty newer decisions are recorded
    And the monitor asked for one page

  Scenario: When the time reserve is reached the rest is read by the next pass
    Given a TTAB monitor and a Reading Room that holds four hundred and fifty new decisions, each page taking thirty seconds
    When the monitor collects
    Then the pass stops early with three hundred decisions, says it ran out of time, and is due again at once
    When the monitor collects at its next scheduled tick
    Then the remaining hundred and fifty decisions are recorded and the monitor has nothing left to resume

  Scenario: A rate-limited source is waited out for as long as it asks
    Given a TTAB monitor and a Reading Room that holds one hundred and fifty new decisions
    And the Reading Room answers its second request with a rate limit and asks for twenty-five seconds
    When the monitor collects
    Then the monitor waited twenty-five seconds and recorded all one hundred and fifty decisions

  Scenario: A stored config that still has the old limits loads and ignores them
    Given a stored monitor config that still says limit 1, maxItems 1 and pagesPerQuery 1
    When the monitor collects
    Then every item the source has is recorded
    And one log line names the ignored fields
