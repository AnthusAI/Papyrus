@backend @editorial
Feature: Constrained rewrite options for editorial findings
  As a publication operator or agent
  I want patch-level rewrite options for findings marked rewrite
  So I can choose constrained edits without rewriting the whole draft

  Scenario: Generate options only for selected findings
    Given a draft file, style profile, diagnosis, and mixed steering decisions
    When rewrite options are generated for findings marked rewrite
    Then options exist only for findings marked rewrite
    And the result does not include rewritten prose
    And the draft file is unchanged
    And the skill constraints forbid evasion tactics

  Scenario: Prefer deletion over filler for empty lead-ins
    Given an empty lead-in finding marked for rewrite
    When rewrite options are generated
    Then at least one option uses empty or minimal replacement
