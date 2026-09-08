@backend @editorial
Feature: Semantic restatement via local sentence embeddings
  As a publication operator
  I want paraphrase clusters in diagnose JSON
  So I can steer repeated claims that 4-gram shingles miss

  Scenario: Three paraphrases of one claim are clustered
    Given a draft that states the same claim three times in different words with no repeated four-word phrase
    And a loadable style profile with semantic restatement enabled
    When I run the diagnose command with an injected embedder that places those sentences in one cluster
    Then there is a concept_restatement group with at least three member sentences
    And that group is not justified only by four-word shingles

  Scenario: Verbatim repeats stay on existing redundancy
    Given a draft that repeats the same four-word phrase in two sentences
    When I run the diagnose command
    Then those sentences are a redundancy group
    And they are not also a concept_restatement group

  Scenario: Check can be disabled
    Given a style profile with semantic restatement disabled
    And a paraphrase draft
    When I run the diagnose command
    Then there is no concept_restatement group
