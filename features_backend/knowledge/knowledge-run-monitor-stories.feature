Feature: The weekly knowledge run can write about the items a site's monitors found
  A site opts in with a monitorStories block in the knowledgeRun settings of its site file, for example a limit of 3. Without the
  block nothing changes: no state in the run, no stack parameter, no setting in the task. With it, the run gains one optional step
  after the trend drafts. The step is off until the stack parameter says it is on, so turning it on is a reviewed change set and not a
  code change. When it runs it calls "papyrus ideas monitor-stories" once, signed as the task role, and that command picks the items
  itself from what the site's monitors delivered. The step reads the OpenAI key from the site's parameter store entry at run time and
  hands it to the command only. It records its cost in the run ledger the way a stage does: one row for the execution, with the
  compute time of the step and the model calls the command made, priced from the usage the model service reported. It never fails the
  run: any problem is logged and the run still ends well.

  Scenario: The step runs the command with the configured number of stories
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    And the site's monitorStories limit is 5
    When the monitor-stories step runs
    Then the command "papyrus ideas monitor-stories" runs once for "shipped" with the limit 5 and the Proposals store
    And the command runs as the task role and the key is only in its environment

  Scenario: A site whose References live in a corpus named differently from the site is read from that corpus
    Given an execution of the knowledge run for "p-apyr-us" that started on 2026-10-28
    And the task is configured with the knowledge corpus key "ai-ml-research"
    When the monitor-stories step runs
    Then the command was given the corpus key "ai-ml-research" beside the site "p-apyr-us"

  Scenario: A site that names no corpus key, or names its own id, uses the command line it always did
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    And the task is configured with the knowledge corpus key "shipped"
    When the monitor-stories step runs
    Then the command was not given a corpus key

  Scenario: Three stories are the default
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    When the monitor-stories step runs
    Then the command runs with the limit 3

  Scenario: The step records its cost in the ledger like a stage
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    And the command drafted 3 stories with 3 model calls
    When the monitor-stories step runs
    Then the ledger has a succeeded "monitor-stories" row for the week "2026-W44" and the execution
    And the row records the model calls, their tokens and their cost, and the compute cost of the step
    And the row records how many stories were filed but not the stories themselves

  Scenario: A command that fails is recorded as a failed row and never fails the run
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    And the command fails
    When the monitor-stories step runs
    Then the ledger has a failed "monitor-stories" row with the error
    And the step logs the failure and exits successfully

  Scenario: Accounting that goes wrong is never in the way
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    And the cost accounting fails
    When the monitor-stories step runs
    Then the ledger has a succeeded "monitor-stories" row without a cost
    And the step logs that cost accounting was skipped

  Scenario Outline: A missing or odd setting skips the step before anything is called or recorded
    Given an execution of the knowledge run for "shipped" that started on 2026-10-28
    And the setting <setting> is <value>
    When the monitor-stories step runs
    Then the step is skipped, nothing is called and the ledger has no row

    Examples:
      | setting                     | value                                 |
      | MONITOR_STORIES_ENDPOINT    | empty                                 |
      | MONITOR_STORIES_ENDPOINT    | https://evil.example.com/graphql      |
      | KNOWLEDGE_OPENAI_KEY_PARAMETER | empty                           |
      | MONITOR_STORIES_LIMIT       | many                                  |
      | MONITOR_STORIES_LIMIT       | 0                                     |
