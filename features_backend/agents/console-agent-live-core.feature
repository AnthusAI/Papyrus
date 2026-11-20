@live-agent @agent-core
Feature: Live console agent core behavior
  Live AppSync and LLM core behavior specs for the Papyrus console responder.

  Background:
    Given live console agent tests are enabled

  Scenario: The console agent responds to hello
    When I run the live console agent smoke scenario "hello"
    Then the live console agent response should include "hello"
    And the live console agent smoke result should include no structured errors
    And the live console agent smoke result should include no tool calls
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent discovers resource documentation progressively
    When I run the live console agent smoke scenario "docs-progressive"
    Then the live console agent smoke result should include tool call "papyrus.docs.list"
    And the live console agent smoke result should include tool call "papyrus.docs.get"
    And the live console agent smoke result should include tool calls in order "papyrus.docs.list" then "papyrus.docs.get"
    And the live console agent model context should include role "user" containing "Use execute_tactus for a strict docs API call-order test."
    And the live console agent model context should include role "system" containing "Tool responses are markdown only, never JSON."
    And the live console agent response should equal "docs-progressive-tested"
    And the live console agent smoke result should include no structured errors
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent retries after unsupported execute_tactus snippet syntax
    When I run the live console agent smoke scenario "unsupported-snippet-retry"
    Then the live console agent smoke result should include tool call "papyrus.docs.get"
    And the live console agent smoke result should include a structured error
    And the live console agent response should equal "unsupported-snippet-retry-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"
