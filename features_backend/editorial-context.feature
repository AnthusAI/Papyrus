Feature: Current editorial context for newsroom agents
  Required publication policy is resolved once and never replaced by stale assignment snapshots.

  Scenario: Resolve current policy for an assignment and its story
    Given editorial records with current publication and section policies
    When the agent resolves editorial context for assignment "a1"
    Then the editorial context includes the current policy and source revisions
    And the editorial context excludes old policy snapshots

  Scenario: Explicit section conflicts are rejected
    Given editorial records with current publication and section policies
    When the agent requests section "business" for assignment "a1"
    Then editorial context fails with "section"

  Scenario: Required publication policy is missing
    Given editorial records with no required publication policy
    When the agent resolves editorial context for assignment "a1"
    Then editorial context fails with "policy"

  Scenario: Unauthorized retrieval cannot become empty policy
    Given editorial records whose reads are denied
    When the agent resolves editorial context for assignment "a1"
    Then editorial context fails with "denied"

  Scenario: A small budget cannot truncate required policy
    Given editorial records with current publication and section policies
    When the agent resolves editorial context with a budget of 10 characters
    Then editorial context fails with "budget"

  Scenario: Worker dispatch ignores caller-supplied policy text
    Given editorial records with current publication and section policies
    When the research worker is prepared with caller-supplied policy text
    Then the worker receives the current resolved policy before dispatch

  Scenario: Publication configuration points at another publication
    Given editorial records with current publication and section policies
    And the hosted canonical corpus belongs to another publication
    When the agent resolves editorial context for assignment "a1"
    Then editorial context fails with "publication"

  Scenario: Unscoped access cannot consume tenant policy
    Given editorial records with current publication and section policies
    And the publication policy belongs to a tenant outside the configured scope
    When the agent resolves editorial context for assignment "a1"
    Then editorial context fails with "tenant"
