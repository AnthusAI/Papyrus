Feature: One correct path that fails clearly
  The Python tools ask the backend for what they need and stop when the backend cannot answer. They do not catch a missing-field
  error and quietly read a different, slower index, and they do not turn an empty answer into a scan of something else. The fix for
  a backend that lacks a field is to deploy it. These scenarios run the real functions against a stand-in for the GraphQL call.

  Scenario: Listing References by import date reads the import-date index and nothing else
    Given the backend answers the import-date index with two current References and one superseded one
    When the References are listed by import date for a corpus
    Then only the two current References come back from the import-date listing
    And the corpus index was not read for the import-date listing

  Scenario: An import-date index with no References is an empty list
    Given the backend answers the import-date index with nothing
    When the References are listed by import date for a corpus
    Then the import-date listing is empty
    And the corpus index was not read for the import-date listing

  Scenario: A backend without the import-date index is an error that names the missing field
    Given the backend does not define the import-date index
    When the References are listed by import date for a corpus
    Then the listing fails and the error names listReferencesByNewsroomFeedAndImportedAt
    And the corpus index was not read for the import-date listing
