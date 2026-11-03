Feature: A web monitor never pays twice for the same search, and says what it paid
  A web monitor asks a search provider for each approved query over a date range. Every ask is paid for, so the collector keeps
  an account of them. Within one pass (a pass can span several runs, because the Lambda's time is short and a stopped pass
  resumes on the next five minute wake) the same query is never asked for the same dates twice, and a page of results that was
  paid for is always read, even when the run that paid for it ran out of time before writing it. Splitting a busy range into
  narrower ones is still allowed: those are different searches. Every run says how many searches it paid for and through which
  provider, and a provider that refuses the key or has used up its plan raises an alarm instead of passing unnoticed.

  Scenario: Splitting a busy range does not ask again for the dates the first ask already covered
    Given a web monitor with one approved query whose last complete pass ended today
    And the provider holds sixty matching articles from the last two days
    When the web monitor collects
    Then the query is asked for the two days, and a full page splits them into one day each
    And the later day is not asked, because the one search for the two days already covered it
    And no query and pair of dates is asked more than once in the pass

  Scenario: A pass stopped by time resumes without repeating any search
    Given a web monitor with two approved queries and seventy matching articles over fourteen days
    And the first run stops on its time budget with its pass unfinished
    When the next five minute wake runs the monitor again until the pass is complete
    Then the searches asked across all the runs are exactly the searches one uninterrupted run would have asked
    And none of them was asked twice

  Scenario: A page the run paid for but could not write in time is read, not bought again
    Given a web monitor whose run receives a page of results and is then out of time before it can write them
    When the pass resumes on the next wake
    Then the resume point holds the paid page of results
    And the next run records those articles without asking the provider again
    And the stored page keeps its scores as whole numbers because the table takes no decimals

  Scenario: Each run and each pass report the searches they paid for
    Given a web monitor whose pass takes two runs
    When both runs finish
    Then each run line and receipt names the searches that run paid for, by provider, and the failures each provider answered
    And the second run's receipt also names the total for the whole pass, which equals every search asked since the pass began

  Scenario: A provider that refuses its key or is out of plan raises the alarm and is not asked again that run
    Given a web monitor whose first provider answers "plan exhausted" and whose second provider answers
    When the web monitor collects three queries
    Then the first provider is asked once and passed over for the rest of the run
    And the second provider answers all three
    And the run logs one "search_provider_failing" line naming the first provider, "plan_exhausted" and the status
    And the template's metric filter counts that line and "papyrus-monitoring-search-provider-failing" alarms on it

  Scenario: When every provider is refused the run fails once and waits for its next scheduled time
    Given a web monitor whose first provider is out of plan and whose second provider refuses its key
    When the web monitor collects with its log captured
    Then each provider is asked once and the run fails
    And the monitor is not due again until its interval or its fixed time of day, not at the next five minute wake
    And both refusals are logged for the alarm

  Scenario: The provider chain is set by one stack parameter
    Given the "WebSearchProviders" stack parameter holds an ordered list of providers
    When it is set to "tavily,perplexity"
    Then the collector's WEB_SEARCH_PROVIDERS names only those two, in that order
    And no monitor config sets its own searchProviders, so OpenAI is no longer asked
