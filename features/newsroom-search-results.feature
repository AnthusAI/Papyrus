@brand-agnostic @search-results-fixtures
Feature: Searching the newsroom goes straight to results, exact words first, each result saying what kind it is and what state it is in
  An editor types into the search box at the top of every newsroom page and presses Enter. The Search page opens already showing the results; there
  is no second form asking for the search again. Results that hold the typed words come first, each marked "Title match" (or "Word match" when the
  word is in the author, link or id), and results that are only close in meaning follow under a "Related" heading, each marked "Related". Every result also
  says in words whether it is Pending, Accepted or Rejected, and every mark has an icon beside its words, so nothing depends on colour. Editors and
  admins see all three states; the public pages and the reader-facing answers still show Accepted References only. Above the results are four
  buttons, Any, Pending, Accepted and Rejected, never a dropdown, and the chosen one says so with a check mark. The page has no borders, reads in one
  column, and does not scroll sideways at 375 pixels. These scenarios use synthetic References in an isolated browser at 375 and 1440 pixels, in Day and Night,
  and never touch production.

  Scenario: The results are on the page the search lands on
    Given a synthetic site where the word "sound" is in the titles of two References, the author of a third, and close in meaning to three more
    When the editor opens the Search page with the word "sound"
    Then the three word matches come first and the three related ones follow under a Related heading, with one request made and no second search needed

  Scenario: Every result says what kind it is and what state it is in, in words
    Given a synthetic site where the word "sound" is in the titles of two References, the author of a third, and close in meaning to three more
    When the editor opens the Search page with the word "sound"
    Then each result is marked Title match, Word match or Related, and Pending, Accepted or Rejected, each with an icon, and nothing has a border or a dropdown

  Scenario: A status button narrows the search
    Given a synthetic site where the word "sound" is in the titles of two References, the author of a third, and close in meaning to three more
    When the editor chooses Rejected, then Pending, then Any
    Then each choice asks the search for that state alone, says it is chosen, and lists only the matching results

  Scenario: Empty, failed, words-only and long answers are said plainly
    Given a synthetic site where the word "sound" is in the titles of two References, the author of a third, and close in meaning to three more
    When the editor searches for words nothing contains, loses the connection, loses only meaning search, and asks for more results
    Then each is said in a sentence, with a button to try again or to show any state, and more results are added without repeats
