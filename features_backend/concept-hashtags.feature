Feature: A concept has a hashtag that people can type and read
  Every concept in the knowledge graph has a key made of its kind and its name, for example "concept--voice-cloning". Its
  hashtag is the name part: "#voice-cloning". People tag References and ideas with hashtags, and the newsroom turns what
  they typed back into the concept. When two kinds share a name, the hashtag is shown with its kind, "#translation (task)",
  so the reader can tell them apart. Typing a full key always names exactly that concept. The Python and the TypeScript
  helpers read the same test vectors, so a hashtag means the same thing in the console and in the backend.

  Scenario: A hashtag is the name part of the key
    Then the hashtag of "concept--voice-cloning" is "#voice-cloning"

  Scenario: A name shared by two kinds is shown with its kind
    Given the concept keys "task--translation" and "concept--translation"
    Then the hashtag of "task--translation" is shown as "#translation (task)"

  Scenario: A typed hashtag finds the concepts it can mean, an exact key first
    Given the concept keys "task--translation" and "concept--translation"
    Then typing "#translation" finds "concept--translation" and "task--translation"
    And typing "#translation (task)" finds "task--translation"
    And typing "#concept--translation" finds "concept--translation"
