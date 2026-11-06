@backend @reference-search
Feature: The References page search finds a Reference again by its words and by its meaning, whatever its state
  An editor types into the one search box on the newsroom References page and gets ordinary Reference cards back, whether the Reference is
  unrated, accepted or rejected. The site's searchReferences query runs two searches together and merges them. The word search looks at each
  Reference's title, authors, link and id. It looks each typed word up in a small word table that is written when a Reference is created or
  changes, so a Reference changed a moment ago is found within seconds; it reads the matching Reference rows and nothing else, never the whole
  table, whether or not the server has just started. The meaning search embeds the query and asks the vector
  index for the nearest Reference summaries in the states the editor chose, cutting the list at the bend of the whole similarity curve, not at its largest single drop, so a question keeps more than its one nearest hit. The
  two are merged in a fixed order, one entry per Reference: an exact title phrase, then every word in the title or authors, then every word anywhere,
  then meaning matches (a Reference found both ways sits first among them and says so), then partial word matches. Question words such as "why"
  and "do" are not searched, each remaining word counts by how rare it is in the site, and a partial match that holds only a small share of a long
  question's distinctive words is left out. A search is answered a page at a time with an opaque cursor. If one search cannot run the other's results are
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

  Scenario: A long question ranks meaning matches above single common-word title matches
    Given a site of 60 References with common title words, and three that answer "why do neural networks forget earlier training" by meaning
    When an editor searches all References for "why do neural networks forget earlier training"
    Then the answers come first, the one found by words and meaning leading and the other two found by meaning
    And no Reference that only shares "neural", "networks" or "training" in its title is listed

  Scenario: A one-word author search is unchanged by the meaning search
    Given a site with 7 Hinton papers and two other References the meaning search would add
    When an editor searches all References for "Hinton"
    Then the 7 author matches come first in the same order as with the word search alone
    And the meaning matches follow them

  Scenario: Meaning search failing still returns the word results for a long question
    Given a site of 60 References with common title words, and three that answer "why do neural networks forget earlier training" by meaning
    And the vector index cannot be reached
    When an editor searches all References for "why do neural networks forget earlier training"
    Then only the Reference whose title covers most of the question's distinctive words is returned, and the meaning search is reported as failed

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

  Scenario: A search can be ordered newest first
    Editors rate References with stars while they curate and come back to find the good ones. A search keeps its relevance order unless the editor
    asks for another: Newest orders the matches by when each arrived. Stars never decide what matches, only the order.
    Given a site of five References that share a word, with stars of 5, 3, none, 5 and 2 and arrivals one day apart, oldest first
    When an editor searches all References for "topic" ordered newest first
    Then the results are the five References, latest arrival first

  Scenario: A search can be ordered by quality
    Given a site of five References that share a word, with stars of 5, 3, none, 5 and 2 and arrivals one day apart, oldest first
    When an editor searches all References for "topic" ordered by quality
    Then the results are the two 5-star References newest first, then 3 stars, then 2 stars, then the one with no stars

  Scenario: A search can ask for a minimum of stars
    Given a site of five References that share a word, with stars of 5, 3, none, 5 and 2 and arrivals one day apart, oldest first
    When an editor searches all References for "topic" ordered newest first with at least 4 stars
    Then the results are the two 5-star References, newest first
    And a minimum of 2 stars is refused, because only 3, 4 and 5 are minimums

  Scenario: A cursor is only good for the ordering and minimum it was made for
    Given a site of five References that share a word, with stars of 5, 3, none, 5 and 2 and arrivals one day apart, oldest first
    When an editor searches all References for "topic" ordered by quality with at least 3 stars, two at a time
    Then the next page continues that ordering
    And the same cursor is refused for another ordering or minimum

  Scenario: A Reference updated a moment ago is found under its new words
    Given a site whose word table follows its References
    When a Reference's title changes and an editor searches for its new title
    Then it is found under the new title and not the old one

  Scenario: A search reads only the rows its words matched
    Given a site with 300 References, six of which share one word
    When an editor searches for that word
    Then six cards are returned
    And the search read six word rows and the six Reference rows they pointed at, and nothing else

  Scenario: An exact word in a title is never missing
    Given a site where a video's title holds the word "sound" among many other results the meaning search prefers
    When an editor searches all References for "sound"
    Then the video is the first result, found by words in its title

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
