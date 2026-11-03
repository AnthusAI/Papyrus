Feature: Semantic search finds its OpenAI key at the shared path when the branch path has none
  A deployed knowledge-query function is told two places to look for its OpenAI key: a
  path for the branch it was deployed from, and a shared path for the whole app. The key
  is stored only at the shared path, so the branch path is simply empty. Semantic search
  looks at the branch path first and, only when SSM says that parameter does not exist,
  looks at the shared path. Any other problem, such as being denied access or being
  throttled, is a real failure and is reported as it happened, never hidden by trying
  somewhere else.

  Scenario: The branch path is empty and the shared path holds the key
    Given a knowledge-query function configured with a branch path and a shared path for its key
    And the key is stored only at the shared path
    When semantic search loads its key
    Then the key is found
    And the branch path was tried before the shared path

  Scenario: The branch path holds the key
    Given a knowledge-query function configured with a branch path and a shared path for its key
    And the key is stored at the branch path
    When semantic search loads its key
    Then the key is found
    And the shared path was never read

  Scenario: Access to the branch path is denied
    Given a knowledge-query function configured with a branch path and a shared path for its key
    And the key is stored only at the shared path
    And reading the branch path is denied
    When semantic search loads its key
    Then loading fails with the access error
    And the shared path was never read

  Scenario: The key is stored nowhere
    Given a knowledge-query function configured with a branch path and a shared path for its key
    When semantic search loads its key
    Then loading fails and names both paths
