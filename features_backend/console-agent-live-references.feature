@live-agent @agent-references
Feature: Live console agent Reference behavior
  Live AppSync and LLM reference discussion/query/quality/note specs.

  Background:
    Given live console agent tests are enabled

  Scenario: The console agent can discuss a specific Reference from corpus
    When I run the live console agent smoke scenario "discuss-reference"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.get"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.get"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-discussion-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can list recent References
    When I run the live console agent smoke scenario "list-recent-references"
    Then the live console agent smoke result should include tool call "papyrus.Reference.list"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-recent-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can fetch details for a specific Reference
    When I run the live console agent smoke scenario "get-specific-reference"
    Then the live console agent smoke result should include tool call "papyrus.Reference.get"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-detail-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can run a knowledge query for one specific Reference
    When I run the live console agent smoke scenario "knowledge-query-single-reference"
    Then the live console agent smoke result should include tool call "papyrus.Reference.get"
    And the live console agent smoke result should include tool call "papyrus.knowledge.query"
    And the live console agent smoke result should include tool calls in order "papyrus.Reference.get" then "papyrus.knowledge.query"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-knowledge-single-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can run a grouped knowledge query for three References
    When I run the live console agent smoke scenario "knowledge-query-three-references"
    Then the live console agent smoke result should include tool call "papyrus.knowledge.query"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-knowledge-group-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"

  Scenario: The console agent can rate Reference quality
    When I run the live console agent smoke scenario "rate-reference-quality"
    Then the live console agent smoke result should include tool call "papyrus.reference.list"
    And the live console agent smoke result should include tool call "papyrus.reference.quality_rate"
    And the live console agent smoke result should include tool call "papyrus.reference.quality_get"
    And the live console agent smoke result should include tool calls in order "papyrus.reference.list" then "papyrus.reference.quality_rate"
    And the live console agent smoke result should include no structured errors
    And the live console agent response should equal "reference-quality-tested"
    And the live console agent smoke result should default to model "gpt-6-luna"
