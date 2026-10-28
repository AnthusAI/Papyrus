Feature: Web-search monitors find new references for each publication through Tavily
  Every publication has its own web monitor (web-<publication>). It asks Tavily the queries its editors approved, for
  the days since its last complete pass, and records what is new. Nothing is cut at an invented number: Tavily answers
  twenty results at most per request, so a busy window is split into narrower date ranges until all of it is read; what
  bounds a pass is the Lambda's time (the next pass resumes) and Tavily's own rate limit.

  Scenario: A busy window is read in full by narrowing the dates
    Given a web monitor for anth-us whose last complete pass was fourteen days ago
    And Tavily holds seventy matching articles over those fourteen days
    When the web monitor collects
    Then all seventy articles are recorded
    And the monitor asked Tavily for narrower date ranges until no range filled a page

  Scenario: Recency comes from the high-water mark, not a fixed window
    Given a web monitor for anth-us that completed a pass on 21 October
    When the web monitor collects five days later
    Then it asks Tavily for results from the day before 21 October up to the new day
    And the high-water mark moves to the start of that pass

  Scenario: A story another source already found is not collected as new
    Given a web monitor for anth-us
    And the Hacker News monitor already collected https://example.org/story-1
    And Tavily returns that story, with tracking parameters, and a new one
    When the web monitor collects
    Then only the new story is recorded

  Scenario: Two publications' web monitors each keep the same story
    Given a web monitor for anth-us
    And a web monitor for shipped that already collected https://example.org/story-1
    And Tavily returns that story
    When the web monitor collects
    Then the story is recorded for anth-us too

  Scenario: Each shared-Cyclotron publication has its own router config
    Given the hn router config lists all the shared publications
    When the web monitors' router configs are built
    Then each lists only its own publication
    And each reuses the hn router's Cyclotron block
    And each holds decisions

  Scenario: Distinctive Mark holds every decision because it has no Cyclotron yet
    Given the hn router config lists all the shared publications
    When the web monitors' router configs are built
    Then the Distinctive Mark config has no Cyclotron block and still validates
    And a router run for it collects and enriches but decides nothing

  Scenario: A held web router posts no decision request
    Given a web monitor for anth-us that collected a story
    And its router config holds decisions
    When the web router runs
    Then no decision request was sent to the Cyclotron
    And the story is still waiting to be decided
