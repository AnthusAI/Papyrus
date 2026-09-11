@backend @editorial
Feature: Diagnostic JSON pass for editorial slop
  As a publication operator or agent
  I want to run a diagnose command on a draft against a style profile
  So I can see what needs changing and steer findings without rewriting the article in this pass

  Scenario: Diagnose a draft without rewriting it
    Given a draft file and a loadable style profile
    When I run the diagnose command
    Then it writes versioned JSON with document_intent, audience, generic_passages, unsupported_claims, repetition_groups, voice_observations, and required_facts
    And each finding has a stable id
    And the findings cover vague claims, empty lead-ins, uniform cadence, list-shaped prose, unsupported certainty, redundancy, and voice mismatch
    And the result does not include rewritten prose
    And the draft file is unchanged

  Scenario: Findings are a steering queue
    Given diagnostic JSON from a completed diagnose pass
    When an operator or agent records skip, rewrite, delete, or keep against a finding id
    Then later option generation can address only the findings marked rewrite
