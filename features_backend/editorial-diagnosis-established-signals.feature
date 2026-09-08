@backend @editorial
Feature: Fuse established density signals into diagnose
  As a publication operator
  I want lexical density and compression as named red flags
  So diagnose uses known techniques before any custom NLP

  Scenario: Catalog names the v1 signals
    Given the editorial signals catalog
    Then it lists lexical density and gzip ratio as implemented
    And it does not list sentence embeddings as a v1 implemented signal

  Scenario: Density summary is present
    Given a loadable style profile with information density enabled
    And a draft of several sentences
    When I run the diagnose command
    Then the JSON includes density with wordCount, sentenceCount, lexicalDensity, and gzipRatio
    And the JSON does not include an embedder field

  Scenario: Long low-content fluff is flagged
    Given a draft longer than the profile minWords that is padded with function words and repeats
    When I run the diagnose command
    Then there is a low_lexical_density or high_compressibility finding

  Scenario: House-voice excerpt is not flagged as fluff
    Given a must-pass excerpt from an Anth.us reference sample longer than minWords
    And the Anth.us style profile
    When I run the diagnose command
    Then there is no low_lexical_density finding
    And there is no high_compressibility finding

  Scenario: Short drafts skip the document-level density flags
    Given a draft shorter than the profile minWords
    When I run the diagnose command
    Then there is no low_lexical_density finding
    And there is no high_compressibility finding
