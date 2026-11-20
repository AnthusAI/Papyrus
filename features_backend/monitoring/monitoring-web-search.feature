Feature: Web-search monitors find new references for each publication through Tavily
  Every publication has its own web monitor (web-<publication>) whose queries are records: each has a text, a
  rationale, who made and approved it, a status and its own high-water mark. A monitor searches only approved,
  active queries, for the days since each query's last complete pass. Nothing is cut at an invented number:
  Tavily answers twenty results at most per request, so a busy window is split into narrower date ranges until
  all of it is read; what bounds a pass is the Lambda's time (the next pass resumes) and Tavily's rate limit.
  Every story is one shared candidate per canonical URL, whatever found it, with provenance.

  Scenario: A busy window is read in full by narrowing the dates
    Given a web monitor for anth-us with one approved query last searched fourteen days ago
    And Tavily holds seventy matching articles over those fourteen days
    When the web monitor collects
    Then all seventy articles are recorded
    And the monitor asked Tavily for narrower date ranges until no range filled a page

  Scenario: A busy single day is still asked as a range Tavily accepts
    Given a web monitor for anth-us with one approved query last searched yesterday
    And Tavily holds thirty matching articles from today
    When the web monitor collects
    Then the monitor narrowed the dates down to a single day
    And no range Tavily was asked starts and ends on the same day, which Tavily refuses
    And today's articles are recorded

  Scenario: An arXiv paper is titled by arXiv, not by its first section heading
    Given Tavily returns an arXiv HTML page titled "1 Introduction" and an ordinary article
    When the results become items
    Then the arXiv item carries the paper's own title from arXiv in one request, and the article keeps its title
    And if arXiv cannot be reached the search engine's title stands

  Scenario: Recency comes from the query's high-water mark, not a fixed window
    Given a web monitor for anth-us whose query completed a pass on 21 October
    When the web monitor collects five days later
    Then it asks Tavily for results from the day before 21 October up to the new day
    And the query's high-water mark moves to the start of that pass

  Scenario: Only approved, active queries are searched
    Given a web monitor for anth-us with one approved query, one unapproved query and one paused query
    When the web monitor collects
    Then Tavily was asked only the approved query

  Scenario: Each query's run is recorded
    Given a web monitor for anth-us whose approved query already found one story
    And Tavily now returns that story and a new one
    When the web monitor collects five days later
    Then the query's run records two results, one new, one duplicate and its credits

  Scenario: A story another source already found is not collected as new
    Given a web monitor for anth-us with one approved query
    And the Hacker News monitor already found https://example.org/story-1
    And Tavily returns that story, with tracking parameters, and a new one
    When the web monitor collects
    Then only the new story is recorded
    And the shared candidate for the first story lists both finds in its provenance

  Scenario: Shared-group web monitors find a story once; Distinctive keeps its own
    Given a web monitor for anth-us with one approved query
    And a web monitor for shipped that already collected https://example.org/story-1
    And Tavily returns that story
    When the web monitor collects
    Then the story is not recorded again for anth-us

  Scenario: Each shared-Cyclotron monitor decides for all six publications
    Given the hn router config lists all the shared publications
    When the web monitors' router configs are built
    Then each shared monitor lists all six publications
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
