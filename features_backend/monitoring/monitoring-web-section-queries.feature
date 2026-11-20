Feature: A web monitor searches one query per newsroom section and one for the whole site
  Each publication's web monitor used to search eight to fifteen topic queries drafted from the whole site. It now searches one
  query for each enabled newsroom section, drafted from that section's own mission, policy, assignment guidance and kill criteria,
  and one query for the whole site, drafted from the publication's mission and policy. The number of queries is exactly the number
  of enabled sections plus one, so the monitor makes about that many paid searches a day. The queries are drafted once: no
  schedule regenerates them. A command shows, for each site, the old queries to retire and the new ones to add, writes nothing
  until it is told to execute, and never deletes: a retired query keeps its history and its high-water mark but is not searched.
  A new query is searched only once someone approves it.

  Scenario: Every enabled section gets one query and the site gets one
    Given a publication with two enabled sections and one disabled section
    When the queries are drafted
    Then there is one drafted query for each enabled section and one for the site, three in all
    And each section's query was drafted from that section's mission, policy, guidance and kill criteria
    And the disabled section has no query

  Scenario: The model must answer with exactly one query
    Given a model that answers a section once with prose and then with a single query
    When the queries are drafted
    Then the drafter asked again and kept the single query
    And an answer with two queries, or none, is refused

  Scenario: A section with no mission is drafted from what it has and flagged
    Given a publication with a section that has a policy but no mission and a section with only a title
    When the queries are drafted
    Then both sections still get a query, because the count stays sections plus one
    And each of the two queries is flagged so an editor can check it

  Scenario: Machines on Machines is read from its own backend and tenant
    Given the p-apyr-us web monitor, which finds for the Machines on Machines backend
    When the queries are drafted
    Then its sections are read for the machines-on-machines tenant and its doctrine from that backend

  Scenario: Executing retires the old queries without deleting them and writes the new ones unapproved
    Given a web monitor with two old topic queries, one of them with a high-water mark
    When the new queries are executed without an approver
    Then both old queries are retired, with a history entry, and keep their high-water mark and their approver
    And the new queries record their origin, who drafted them, and their section or the site
    And none of the new queries is searched yet

  Scenario: Approving makes the new queries searchable
    Given a web monitor with two old topic queries
    When the new queries are executed with an approver
    Then exactly the section queries and the site query are searched
    And the old queries are not searched

  Scenario: A dry run shows the plan and writes nothing
    Given a web monitor with an old topic query and an editor-written query
    When the plan is made without executing
    Then it lists the old query to retire and the new queries to add
    And the editor-written query is kept
    And it reports the paid searches a day that the monitor will make
    And the table is unchanged

  Scenario: Queries are drafted once and a later run adds only what is missing
    Given a web monitor whose per-section queries have been executed and approved
    When the plan is made again
    Then nothing is retired or added and the model is not asked
    When a section is renamed and another section is added
    Then only the new section gets a query, and the renamed section keeps its own

  Scenario: A section that is switched off loses its drafted query
    Given a web monitor whose per-section queries have been executed and approved
    When one section is disabled and the plan is made
    Then that section's drafted query is retired

  Scenario: Editor-written queries are retired only on request
    Given a web monitor with an editor-written query
    When the plan is made with and without the request to retire editor queries
    Then the editor-written query is kept unless it is asked for

  Scenario: The collector searches only active approved queries
    Given a web monitor with an active approved query, a paused query and a retired query
    When the web monitor collects
    Then Tavily was asked only the active approved query

  Scenario: A new query's first search is one request, not a backlog
    Given a web monitor whose new section query has never been searched
    And Tavily holds forty matching articles over the last five days
    When the web monitor collects
    Then Tavily was asked that query once, with no date range and its usual page size
    And the query's high-water mark is set to the start of that pass
