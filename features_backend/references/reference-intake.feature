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

  # The Newsroom's Add dialog sends only the web address. The server fills in the rest, so an editor never has to invent a title,
  # a rationale or a corpus, and the address becomes a real pending Reference that the References page lists at once.
  Scenario: The Add dialog sends only an address
    Given an isolated publication intake backend with one canonical corpus
    When its editor registers an address with nothing else
    Then the address is a pending Reference in the publication's own corpus
    And its title is the address and its rationale says an editor added it from the Newsroom
    And adding the same address again returns the same Reference

  Scenario: An address alone is refused when the publication cannot be told from the backend
    Given an isolated publication intake backend
    When its editor registers an address with nothing else
    Then the registration is refused and nothing is written

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

  Scenario: A catalog from the command line is sent one source at a time and reported as it goes
    A source takes 6 to 12 seconds on the server, so a whole batch in one request can outlast the
    client's read timeout and leave nobody knowing which sources were recorded.
    Given a catalog file of 31 sources and a signed-in editor session
    When the editor runs references create-from-catalog
    Then the command sent 31 requests of one source each, in catalog order
    And it printed one created line per source, numbered "1/31" to "31/31"
    And it ended with a summary of 31 created, 0 already existed and 0 not confirmed

  Scenario: One source that times out is reported and the rest are still sent
    Given a catalog file of 3 sources and a signed-in editor session
    And the second request times out
    When the editor runs references create-from-catalog
    Then the command sent 3 requests of one source each, in catalog order
    And it printed a failed line for "2/3" naming the source
    And it ended with a summary of 2 created, 0 already existed and 1 not confirmed
    And the command failed telling the editor to run the same command again

  Scenario: Running the same catalog again returns the same records and says they already existed
    Given a catalog file of 3 sources and a signed-in editor session
    When the editor runs references create-from-catalog twice
    Then both runs reported the same Reference ids, the second as already existing

  Scenario: A source a person already accepted keeps its status and the output says it already existed
    The run asks for pending, but a Reference that is already recorded is returned as it is. The output must
    not read as if this run had created it as accepted.
    Given a catalog file of 3 sources and a signed-in editor session
    And the catalog source "paper-2" is already recorded and accepted
    When the editor runs references create-from-catalog
    Then it printed an already-existed line for "2/3" showing the status accepted and that pending was not applied
    And the Reference "paper-2" is still accepted on the server
    And it ended with a summary of 2 created, 1 already existed and 0 not confirmed

  Scenario: A backend that does not say whether a Reference was created is reported as unknown
    The CLI needs a backend at the same or later version. Without the field it does not guess.
    Given a catalog file of 1 sources and a signed-in editor session
    And the backend does not report whether a request created a Reference
    When the editor runs references create-from-catalog
    Then it printed that the outcome of "1/1" is unknown because the backend predates this CLI
    And the summary counts 1 outcome as unknown

