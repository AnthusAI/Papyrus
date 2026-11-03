@backend @reference-search
Feature: The References page search finds a Reference again by its words and by its meaning, whatever its state
  An editor types into the one search box on the newsroom References page and gets ordinary Reference cards back, whether the Reference is
  unrated, accepted or rejected. The site's searchReferences query runs two searches together and merges them. The word search looks at each
  Reference's title, authors, link and id; it keeps its own index in memory, reads every current Reference once when it starts, and afterwards
  reads only the References changed since, so a Reference changed a moment ago is found. The meaning search embeds the query and asks the vector
  index for the nearest Reference summaries in the states the editor chose, cutting the list where the similarity drops most. The two are merged by
  Reciprocal Rank Fusion, one entry per Reference: a Reference whose every word is found sits above one found only by meaning, and a Reference found
  both ways sits first and says so. A search is answered a page at a time with an opaque cursor. If one search cannot run the other's results are
  still returned with that search's status. Only editors and admins may ask, and the command line asks the same query without writing anything.
  Nothing here touches production: the site and the vector index are in memory.

  Scenario: An exact author name finds a rejected Reference
    Given a site with an unrated, an accepted and a rejected Reference, the rejected one by "Marta Okafor"
    When an editor searches all References for "Marta Okafor"
    Then the rejected Reference is the only result, found by words in its authors
    And it carries its whole record, so the page can draw an ordinary card

  Scenario: A word from a title finds an unrated Reference
    Given a site with an unrated, an accepted and a rejected Reference, the rejected one by "Marta Okafor"
    When an editor searches unrated References for "notebooks"
    Then the unrated Reference is the only result, found by words in its title
    And choosing rated References instead finds nothing for that word

  Scenario: A conceptual phrase finds a Reference by meaning only
    Given a site where a Reference about agent recall has no words in common with "long-term remembering"
    When an editor searches all References for "long-term remembering"
    Then that Reference is a result, found by meaning and not by words
    And the vector index was asked for summary vectors in the unrated, accepted and rejected states, at most 100

  Scenario: A Reference found by both words and meaning ranks first and says so
    Given a site with one Reference whose title has the words and whose summary has the meaning, one with only the words, and one with only the meaning
    When an editor searches all References for "agent memory"
    Then the Reference found both ways is first and says it was found by words and by meaning
    And the Reference found only by words is next, and the one found only by meaning is last

  Scenario: Meaning search failing still returns the word results
    Given a site where the vector index cannot be reached
    When an editor searches all References for "notebooks"
    Then the word results are returned
    And the answer says the word search worked and the meaning search failed, in a sentence that is safe to show

  Scenario: Both searches failing returns no cards and says so
    Given a site where neither the References nor the vector index can be reached
    When an editor searches all References for "notebooks"
    Then no cards are returned and both searches are reported as failed

  Scenario: Paging never repeats a card
    Given a site with 60 References that share a phrase
    When an editor reads every page of 24 for that phrase, following the cursor each time
    Then every Reference appears exactly once and the last page has no cursor
    And a cursor from a different search or show choice is refused

  Scenario: A Reference updated a moment ago is found without reading the others again
    Given a site whose search has already read its References once
    When a Reference's title changes and an editor searches for its new title
    Then it is found under the new title and not the old one
    And only References changed since the last read were read, with a short overlap

  Scenario: The first search after a start reads every current Reference once and times it
    Given a site with 5 current References, one of them archived, read two at a time
    When an editor searches for the first time
    Then every page was read, the archived Reference is left out, and the time it took is logged

  Scenario: The search answers when the resolver names its field at the top of the event
    Given the search is asked for through an Amplify resolver by an editor
    Then the search runs instead of the knowledge query

  Scenario: A person who is not an editor or admin is refused
    Given the search is asked for by someone in the reader group
    Then the search is refused with a Not Authorized message
    And the deployed schema allows only the editor and admin groups to ask, and no guest or identity-pool access

  Scenario: The command line search writes nothing
    Given a signed-in editor with no AWS credentials and no AWS library, who can search References
    When the editor searches References from the command line with "papyrus references search agent memory --show rated"
    Then the command succeeds and lists each Reference with how it matched
    And every request sent was a query, never a mutation, and carried the editor's sign-in token and no AWS signature
