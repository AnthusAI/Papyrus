@live-agent @agent-curation
Feature: Live console agent Reference curation behavior
  Live AppSync and LLM reference editorial and re-curation specs.

  Background:
    Given live console agent tests are enabled

  Scenario: The console agent can run Reference accept editorial cycle
    When I run the live console agent smoke scenario "review-reference-curation-accept"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.curation_review"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.curation_review"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-curation-accept-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can run Reference reject editorial cycle
    When I run the live console agent smoke scenario "review-reference-curation-reject"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.curation_review"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.curation_review"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-curation-reject-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can run Reference archive editorial cycle
    When I run the live console agent smoke scenario "review-reference-curation-archive"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.curation_review"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.curation_review"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-curation-archive-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can run Reference reopen editorial cycle
    When I run the live console agent smoke scenario "review-reference-curation-reopen"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.curation_review"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.curation_review"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-curation-reopen-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can queue and inspect Reference re-curation
    When I run the live console agent smoke scenario "curate-reference-refresh"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.curation_start"
    And the live console agent smoke result should include tool call "papyrus.reference.curation_status"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.curation_start"
    And the live console agent model context should include execute_tactus tool call entries
    And the live console agent model context should include role "user" containing "Use execute_tactus for async Reference re-curation test."
    And the live console agent model context should include role "tool" containing "papyrus.reference.curation_start"
    And the live console agent model context should include role "tool" containing "papyrus.reference.curation_status"
    And the live console agent model context should include tool result entries in order "papyrus.reference.curation_start" then "papyrus.reference.curation_status"
    And the live console agent smoke result should include no tool call "papyrus.reference.quality_rate"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should match regex "^assignment[-_][A-Za-z0-9_-]+$"
    And the live console agent smoke result should default to model "gpt-6-luna"
