@backend @newsroom @context
Feature: A cloud procedure run leaves a trace of what the model was told and what it ran
  A research or reporting procedure runs in the cloud, out of sight. So that an editor can audit what an
  agent did, the run's output is turned into trace files: one record for every call to the model, with the
  messages it was sent, and one record for every piece of Tactus code the agent executed.

  Scenario: Cloud procedure traces include model-call message history and execute_tactus call traces
    Given sample cloud procedure stdout with one LLM payload and one execute_tactus call
    When I build llm-context trace artifacts
    Then the summary includes one llm call and one execute_tactus call
    And llm-context calls.jsonl exists with one record
    And llm-context execute_tactus_calls.jsonl exists with one record
