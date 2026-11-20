Feature: What the cloud knowledge run costs
  The scheduled knowledge run is an unattended pipeline in AWS, and nobody should have
  to guess what a week of it costs. Every stage records, in its row of the run ledger,
  the cost of the Fargate task it ran in (seconds, vCPU and memory, priced at the ARM
  rate for US East) and of the language-model calls it made, read from the usage the
  model API reported and priced from the model price table. The last stage adds the
  stages up into one run-level row and a report in the state bucket, and an operator
  reads all of it with `papyrus knowledge runs`. The figures are estimates, never a
  bill. A figure that cannot be known is recorded as null with the reason, not as zero,
  and a problem in the accounting never fails a stage.

  Background:
    Given the cloud run for the publication "shipped" in execution "manual-1" started on 2026-10-26

  Scenario: A stage records the Fargate cost of the task it ran in
    When the stage "corpus-sync" runs
    Then the cost of "corpus-sync" says it ran 90 seconds on 4 vCPU and 16 GB
    And the compute cost of "corpus-sync" is the ARM rate for that size and time
    And the cost of "corpus-sync" says it made no model calls and its total is the compute cost

  Scenario: The AI review records the tokens and dollars the model API reported
    Given the AI review will run with a model that reports 1000 input tokens, 200 of them cached, and 100 output tokens per call
    When the AI review stage runs
    Then the cost of "ai-review" counts the model calls and their tokens
    And the model cost of "ai-review" is priced from the model price table
    And the cost of "ai-review" lists the calls by model
    And the total cost of "ai-review" is compute plus model

  Scenario: A response without usage still counts as a call, with no price and a reason
    Given the AI review will run with a model that reports no usage
    When the AI review stage runs
    Then the cost of "ai-review" counts the model calls and says the price is unknown because the responses carried no usage
    And the cost of "ai-review" is marked partial and its total is the compute cost

  Scenario: A failed attempt is paid for and the retry adds to it
    Given the command "knowledge snapshot" fails
    When the stage "snapshot" runs
    Then the stage failed
    And the ledger row of "snapshot" holds the cost of 90 seconds
    When the command "knowledge snapshot" works again
    And the stage "snapshot" runs
    Then the cost of "snapshot" says 2 attempts and 180 seconds

  Scenario: A problem in the accounting does not fail the stage
    Given the task size cannot be read
    When the stage "snapshot" runs
    Then the stage succeeded
    And the ledger row of "snapshot" holds no cost

  Scenario: The last stage sums the run into a run row and a report in the state bucket
    When every stage of the run has succeeded
    Then the run row says succeeded with the total of the stages and 900 seconds of compute
    And the state in S3 holds "runs/2026-W44/cost-manual-1.json"
    And the report lists every stage

  Scenario: A run that stops early has no run row
    Given the command "knowledge snapshot" fails
    And the stage "corpus-sync" has run
    When the stage "snapshot" runs
    Then the stage failed
    And there is no run row
    And the ledger row of "corpus-sync" holds a cost

  Scenario: The runs command prints each run and stage with cost and duration
    Given every stage of the run has succeeded
    When an operator lists the runs with "papyrus knowledge runs --site shipped --last 3"
    Then the output starts with the week, the execution, the status and the total cost
    And the output has a line for every stage with its time and cost

  Scenario: The runs command can print JSON and limits how many runs it shows
    Given every stage of the run has succeeded
    And every stage of execution "manual-2" has succeeded
    When an operator lists the runs with "papyrus knowledge runs --site shipped --last 1 --json"
    Then the output is JSON for 1 run with its total cost
