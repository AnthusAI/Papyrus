@backend @reference-search @reference-word-index
Feature: The words of every Reference are kept in a small table of their own, written when a Reference arrives or changes
  The newsroom search finds a Reference by an exact word of its title (or its authors, address or id) and by the start of a word. For that, each
  Reference's words are written to a word table, one row per word per Reference, by a function that listens to changes on the Reference table. The
  search looks each typed word up in that table and reads only the Reference rows the words point at, so it never reads the whole table and nothing
  runs on a timer. A change that alters no word, such as a vote, a star or a prediction, writes nothing. A newer version of a Reference is never
  undone by a late message about an older one. A site that existed before the table is filled once, by an operator command that shows what it would
  do before it does anything.

  Scenario: A Reference that arrives is searchable by the words of its title
    Given a site whose word table follows its References
    When a Reference titled "I discovered a sound that leaks your exact location" arrives
    Then searching for "sound" finds it, and so does searching for "leak" as the start of a word

  Scenario: A vote writes no word rows
    Given a site whose word table follows its References
    When an editor accepts a Reference and gives it four stars
    Then no word row was written or deleted

  Scenario: A late message about an older version never undoes the newer one
    Given a site whose word table follows its References
    When a Reference gets a second version with a new title and the first version's change to superseded arrives after it
    Then searching finds it under the new title and not the old one

  Scenario: The one-time backfill shows what it would do and writes nothing until told to
    Given a site with a pending, an accepted, a rejected and an archived Reference and no word rows
    When the operator runs the backfill without writing
    Then it reports three References to index and writes no rows
    And when the operator runs it with writing every state is searchable and a second run writes nothing
