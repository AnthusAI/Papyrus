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

  # A backend that carries a tenant id is refused by default, because knowledge data has no tenant isolation.
  # A site that has its own backend and exactly one publication says so with PAPYRUS_SINGLE_PUBLICATION_BACKEND=true.
  # The flag is read exactly: anything other than the text "true" leaves it off. It never lifts a refusal for a session
  # that carries a tenant, and it never makes a non-editor an editor. Whoever adds a second publication to such a
  # backend must remove the flag first.

  Scenario: An editor of a single-publication backend that carries a tenant can register a source
    Given an isolated publication intake backend
    And the backend carries a tenant and declares that it serves a single publication
    When its editor registers a reporting source
    Then the source is pending with attributable provenance

  Scenario: A backend that carries a tenant and does not declare one publication refuses its editor
    Given an isolated publication intake backend
    And the backend carries a tenant and does not declare that it serves a single publication
    When intake is requested with a valid editor session
    Then no intake data is written
    And the refusal names the setting that declares a single publication

  Scenario Outline: The declaration is read exactly
    Given an isolated publication intake backend
    And the backend carries a tenant and declares "<value>" for the single publication setting
    When intake is requested with a valid editor session
    Then no intake data is written

    Examples:
      | value |
      | True  |
      | 1     |
      | yes   |
      | false |

  Scenario Outline: The declaration never lifts the refusal of a session that carries a tenant
    Given an isolated publication intake backend
    And the backend carries a tenant and declares that it serves a single publication
    When intake is requested with an editor session whose token has the "<claim>" claim
    Then no intake data is written

    Examples:
      | claim            |
      | tenantId         |
      | custom:tenantId  |

  Scenario: The declaration does not make a reader an editor
    Given an isolated publication intake backend
    And the backend carries a tenant and declares that it serves a single publication
    When intake is requested with a reader role
    Then no intake data is written
