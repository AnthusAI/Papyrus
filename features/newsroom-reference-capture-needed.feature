@brand-agnostic @reference-feed-fixtures
Feature: People capture what we could not: accepted References without their content are easy to find and fix
  Some accepted References are only a title and an address, because the page sat behind an I'm-not-a-robot gate or a paywall. It is worth a
  person's effort to collect the highest rated of them, by uploading a PDF or selecting everything on the page and pasting it. Every Reference
  records how much of its content the newsroom holds (full, thin, none or running; empty means none), and only full counts as captured. The
  References page has two filters that find them. Reviewed (Any, Accepted, Yes, No) says whether someone has answered a Reference: Accepted
  keeps only the ones accepted and never a rejected one, Yes means accepted or rejected, No means nobody has answered; these are the words
  the old Show choice (Unrated, All, Rated) used, with the same saved values, so nobody's choice resets. Captured (Any, Yes, No) says whether we
  hold the content: No keeps a thin capture, one that is still running and one with nothing but an address, in any Sort, in the feed and in
  a search. A capture an editor doubts counts as not captured, and one an editor says is complete counts as captured. The newsroom home lists
  a few accepted References that need a capture, most stars first and then newest, the unstarred after every starred one, never a rejected one
  or one still being captured, with the words "We could not collect this. Upload a PDF or paste the text." and the reason when it is known, and a
  See all that opens the References page on Reviewed Accepted, Captured No and Sort Newest, so the unstarred ones are there too, without changing what the editor saved. When a person
  pastes or uploads the text, the Reference leaves the list without a reload. These scenarios use synthetic References in an isolated browser at
  375 and 1440 pixels and never touch production.

  Scenario: Reviewed and Captured are labelled rows of buttons with icons and words, and Reviewed keeps its saved values
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the editor looks at the Reviewed and Captured controls at 375 and 1440 pixels
    Then Reviewed reads Any, Accepted, Yes and No and Captured reads Any, Yes and No, each a button with a Lucide icon and words, with no drop-downs and no borders
    And the saved values of Reviewed are still all, accepted, rated and unrated, Reviewed is No and Captured is Any by default, and nothing scrolls sideways

  Scenario: Captured Yes and No filter the feed in every sort, and thin, running and empty all count as not captured
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the editor chooses Captured Yes, then Captured No, under Quality with Reviewed Any
    Then Yes lists only the ones whose content is held in full, and No lists the thin, the running and the ones with no state at all, in the same order
    And the choice is remembered in this browser

  Scenario: Reviewed Accepted lists the accepted References and never a rejected one
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the editor chooses Reviewed Accepted, then Reviewed Yes, and combines Accepted with Captured No
    Then Accepted leaves out the rejected Reference that Yes lists, and Accepted with Captured No lists the accepted ones we could not collect

  Scenario: A doubted capture counts as not captured and an editor's complete counts as captured
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the stored capture state is worked out from attachments, a card with a subscribe phrase at its end, an editor's complete, an editor's incomplete and a pasted text
    Then a doubted capture is thin, an editor's complete makes it full, an editor's incomplete or incorrect makes it thin, text a person pasted is full, and an empty or unknown value reads as none

  Scenario: Filtering goes on past pages that filter to nothing
    Given a synthetic site where sixty captured References arrived after the three we could not collect
    When the editor chooses Newest and Captured No
    Then the feed keeps asking for pages until the three are reached, and none of the captured ones is listed

  Scenario: Search takes Captured and Reviewed Accepted too
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the editor searches with Captured No and then chooses Reviewed Accepted
    Then the search was asked for Captured No and for Accepted, the matches are the ones that fit, and choosing Reviewed during a search is not saved

  Scenario: The empty state says what found nothing and offers a way out
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the editor chooses Reviewed Accepted, the minimum 5 and Captured Yes
    Then the page says "Nothing here has 5 stars and has been captured." with Show any stars and Show any Captured buttons, and Show any Captured lists the Reference again

  Scenario: A page address opens a view for one visit without changing what the editor saved
    Given a synthetic site where some References are captured, some are thin, one is still being captured and some are only an address
    When the editor opens the References page on Reviewed Accepted, Captured No and Sort Quality from an address
    Then those choices are pressed and listed, nothing was saved to the browser, and changing a control inside that view is not saved either

  Scenario: The home page lists accepted References we could not collect, best first, with a way to fix them
    Given an isolated newsroom home where accepted References have stars, some are still capturing, one is rejected and one is captured
    When the editor opens the newsroom home at 375 and 1440 pixels
    Then three are listed, most stars first and newest first within a level, and the running, the rejected and the captured ones are left out
    And each says "We could not collect this. Upload a PDF or paste the text." with the reason when it is known, the header and a To capture pill count them, and How this is ordered says why
    And See all links to the References page on Reviewed Accepted, Captured No and Sort Newest, nothing scrolls sideways and nothing has a border

  Scenario: Pasting the text removes the Reference from the home list without a reload
    Given an isolated newsroom home where accepted References have stars, some are still capturing, one is rejected and one is captured
    When the editor opens the first one, chooses Paste or correct the text, says the capture was incomplete and saves the text
    Then the capture is saved with the text and the verdict, the Reference leaves the list at once, and the next one joins behind the new items button

  Scenario: A site that cannot read the list still shows the rest of the home page
    Given an isolated newsroom home where accepted References have stars, some are still capturing, one is rejected and one is captured
    When the read of the capture list fails
    Then no capture cards and no See all are shown and the other cards are untouched

  Scenario: Which References the home page reads, and in what order
    Given records held in memory with stars, a capture state, a status and a version state
    When the home list is read from the star partitions and then from the rated partition
    Then the star levels come first, the unstarred follow newest first, a read that fails still lists what was found, and the reader stops once it has enough
