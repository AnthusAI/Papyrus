@reference-intake
Feature: Publication-scoped pending Reference intake
  Editors can register reporting sources using their existing publication session.
  Intake preserves source provenance without granting generic model writes.

  Scenario: Authorized editor registers and consults a source
    Given an isolated publication intake backend
    When its editor registers a reporting source
    Then the source is pending with attributable provenance
    And its returned record can be linked as consulted without changing the story

  Scenario: Repeat intake preserves the first source record
    Given an isolated publication intake backend
    When its editor repeats intake using a canonical equivalent URL
    Then the same immutable source and provenance are returned

  Scenario Outline: Intake rejects unauthorized publication access
    Given an isolated publication intake backend
    When intake is requested with <violation>
    Then no intake data is written
    Examples:
      | violation                 |
      | no identity               |
      | a reader role             |
      | another issuer            |
      | another publication       |
      | another corpus            |
      | a caller selected tenant  |
