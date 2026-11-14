Feature: The editorial check reads a saved version's language, and asks for the editorial context only with arguments the backend declares
  Every save path checks the version it saved (`papyrus editorial check-version`, the check built into `stories save-version`). The check reads the saved
  version's row through its own narrow query, so that query must ask for the version's language: a row that has its language is never refused as having
  none because the check did not ask for it.

  The check also reads the site's editorial context. A site's own backend has no tenant to name, so the query carries no tenant argument and stays valid
  on a backend released before that argument existed (GraphQL refuses an argument the schema does not declare, even as null). Only a tenant on the shared
  stack is named.

  Scenario: The check reads the language of the version it checks
    Given a saved Story version written in "en" in its own language group
    When the editorial check reads the saved version
    Then the version is read with its language "en" and its language group
    And the language the check uses for it is "en"

  Scenario: A site's own backend is asked for the editorial context without a tenant argument
    When the check reads the editorial context of a site that has its own backend
    Then the query sent names no tenant argument

  Scenario: A tenant on the shared stack is named when the editorial context is read
    When the check reads the editorial context of the tenant "mom" on the shared stack
    Then the query sent names the tenant "mom"
