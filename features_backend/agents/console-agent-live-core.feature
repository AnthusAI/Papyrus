@live-agent @agent-core
Feature: The console agent answers a person in the live newsroom
  These scenarios talk to the real console agent on a deployed site with a real model behind it, so they run only when live agent
  tests are turned on and never in the ordinary test run. They show the basics a person relies on: the agent answers a greeting
  without calling a tool, reads its own documentation a piece at a time as it needs it, and tries again when the first thing it
  wrote is not supported.

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
