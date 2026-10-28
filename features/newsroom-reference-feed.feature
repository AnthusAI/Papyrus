@brand-agnostic @reference-feed-fixtures
Feature: The References page is a news feed ranked by what the Cyclotron expects the editor to accept
  References open as a feed in a responsive grid, like a news app: a larger lead card, then cards with a picture, a title, a one-line
  dek, the source and its age, the Cyclotron's prediction (Accept or Reject with its confidence and an icon) and the editor's own
  Accept and Reject. The order is the Cyclotron's prediction: the items it expects the editor to Accept most surely come first, the
  items with no prediction sit in the middle, and the strongest predicted Rejects come last. Age fades a prediction toward "not sure"
  and never to the bottom, at a pace learned from how old the editor's accepted References were when accepted; with fewer than ten
  accepted examples nothing is guessed. A card the editor rates stays where it is for the rest of the visit, showing the answer and
  whether the Cyclotron matched it; on the next visit it is under Rated. Unrated items past their freshness move to an Earlier section at
  the bottom and can still be rated. The page shows its shell and card skeletons at once instead of a checking screen, and a return
  visit shows the last saved cards while the live read runs. These scenarios use synthetic References in an isolated browser at 375 and
  1440 pixels and never touch production.

  Scenario: The strongest predictions are first and the strongest Rejects are last
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then the order runs from the strongest Accept, through the item with no prediction, to the strongest Reject
    And the first card is the large lead card, and the grid has one column on a phone and three or more on a desktop
    And every card shows its title, dek, source, age, the Cyclotron's Accept or Reject with its confidence and icon, and large Accept and Reject buttons
    And a title shows without the site name a page tacks on its end, such as " | Brookings" or " | Poverty and Development | Al Jazeera"
    And nothing scrolls sideways and there are no drop-downs

  Scenario: Age fades a prediction toward not sure, at a pace learned from the editor's own accepts
    Given References whose accepted examples show how quickly the editor acts
    When the feed is ranked
    Then an old prediction keeps only part of its distance from not sure and never falls below a fresh Reject
    And with fewer than ten accepted examples there is no fading and no Earlier section
    And a card rated this visit does not move any other card

  Scenario: A rated card stays in place, shows whether the Cyclotron matched, and is under Rated on the next visit
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor accepts a card, then rejects it with a reason, and rejects a card the Cyclotron expected to be rejected
    Then each rated card stays in its place and shows Saved
    And the Cyclotron's chip says Match with a check or Miss with a cross, in words and an icon as well as colour
    And Rejecting asks for a reason in words and changes nothing until one is chosen
    And the Rated tab lists the most recent answer first, and the next visit lists the answered cards there

  Scenario: The rating area is one grid, with each of your buttons directly under the matching Cyclotron cell
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then the Cyclotron row and the You row share the label, Accept and Reject columns exactly, on a card and in the review card, at 375 and 1440 pixels
    And on a card as narrow as 240 pixels every icon, word and percentage fits inside its cell, the confidence wrapping onto its own line
    And a confidence bar spans both columns, centred at 50%, filling toward Accept for an Accept-leaning prediction and toward Reject for a Reject-leaning one
    And the fill's length is the prediction's distance from 50% doubled, and with no prediction the bar is empty and says No prediction
    And before a vote the predicted cell is neutral with a Check or X icon

  Scenario: After a vote the prediction turns green with a CircleCheck for a match or red with a CircleX for a miss
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor votes with the Cyclotron's side and against it
    Then the matching prediction cell is green with a CircleCheck and says Match, and the confidence bar is green
    And the differing prediction cell is red with a CircleX and says Miss, and the confidence bar is red
    And the chosen button is filled and the other is quiet, and tapping the chosen one does not unselect it

  Scenario: Unrated items past their freshness move to Earlier at the bottom and can still be rated
    Given References older than three times the learned freshness
    When the editor opens the feed at 375 and 1440 pixels
    Then they appear in an Earlier section after everything in the feed, and under the Earlier tab
    And an Earlier card can be rated and stays where it is

  Scenario: The feed is flat, rounded and borderless, with large section headings
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then no card, tab, pill, chip, panel or skeleton has a border, an outline or a rule, and surfaces differ only by tone
    And cards are rounded rectangles with a full-bleed picture across the top, and pills are fully rounded
    And the feed has the sections Top predictions, More for you and Least likely in large type with no lines between them
    And on a phone the first card's picture is on the first screen

  Scenario: A picture that cannot load becomes a tile with the source name
    Given References whose pictures load, fail, or were never found
    When the editor opens the feed at 375 and 1440 pixels
    Then the pictures are lazy, in a fixed frame and requested with no referrer
    And a missing or failing picture shows a soft gradient tile with the source's mark and name
    And each source's mark is the icon the newsroom found for it, or its first letter when there is none

  Scenario: The newsroom finds a source's real icon instead of guessing
    Given a source home page that declares its icons
    When the newsroom looks for that source's icon
    Then it prefers the touch icon, then the largest declared size, and ignores single-colour mask icons
    And it falls back to /favicon.ico only when that is more than an empty placeholder
    And only real host names that resolve to public addresses are ever fetched

  Scenario: The page shows its shell and card skeletons at once, never a checking screen
    Given the References are still loading
    When the editor opens the feed at 375 and 1440 pixels
    Then the page header, the tabs and card skeletons are on screen and no text says it is checking credentials

  Scenario: A return visit shows the last saved cards, read only, until the live read arrives
    Given this browser saved the last feed it showed
    When the editor opens the References page while the session is still being confirmed
    Then the saved cards are shown at once with a note that they are the last view
    And answering is switched off with the reason in words, and a saved copy never answers on its own
    And the saved copy and the session summary expire, survive a blocked or full browser store, and are wiped on sign-out

  Scenario: The ranking is explained in plain words with this site's own numbers
    Given the feed is open
    When the editor opens how this feed is ranked
    Then it explains best bets first, confidence, fading toward not sure, Earlier and why a rated card stays put
    And it says how many accepted examples have been learned from, or how many more are needed

  Scenario: The detail pane reads top to bottom: what the item is, then the rating, then what was captured
    Given References where one has full stored text, one only a teaser, and one nothing but its link
    When the editor opens each of them
    Then the title comes first, then the source's own blurb when it has one, the link, the badges and the summary, then Accept and Reject with the Why box
    And the source's live preview sits right under its link only when the source allows being shown in a frame, with no heading and no empty box otherwise
    And our captured record and the import details come after the rating
    And the record says "Full text captured" with the stored text, its word count and any structured extraction, and the summary is not repeated there
    And the stored text is Markdown shown formatted, with headings and lists as such and no Markdown syntax showing through
    And the record says "Only 63 words — may be a teaser or paywalled" for the teaser, and "No text captured" for the one with nothing
    And each state has its own Lucide icon as well as its words, and the record sits above the source preview
    And every grid card carries a small badge saying Full text, how many words, or No text, before the item is opened

  Scenario: A vote, then a reason, ends up as one decision, and both the card and the detail pane show it
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor accepts on the grid card and then types a reason in the detail pane
    Then the pane shows the vote, the green match state, and the reason is saved onto the same decision after a pause or on blur, with a Saved tick in both places

  Scenario: A reason, then a vote, ends up as one decision that carries the reason, and a typed reason is never lost
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor types a reason in the detail pane before voting, then votes
    Then the vote carries the reason, a Reject with a typed reason saves at once under "Other", a Reject with no reason at all waits for one, and a failed save keeps what was typed

  Scenario: A reason chosen in the pane shows on the card, and a Reject waiting for its reason is waiting in both
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor rejects on the card and chooses the reason in the detail pane
    Then both show the Reject, the card shows the reason and the red or green match state with its icon

  Scenario: Previous and Next scroll the grid to the same item and select it
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens a card and steps through the queue with Next and Previous
    Then the grid scrolls smoothly so the selected card stays in view, on a tinted surface with a left accent bar and no outline
    And opening a card from the grid selects it too

  Scenario: The grid stays put while the editor selects, rates and the data refreshes
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor selects five items in turn, rates two, and a background refresh changes the predictions and adds a new item
    Then every card keeps its order and its position and size, and the grid does not scroll, at 375, 900 and 1440 pixels
    And the column count stays fixed while the detail pane is open, and the pane's place is reserved beside the grid from the tablet width up, so opening it moves nothing, while below that the detail is a sheet
    And the feed order is taken once per visit, so a re-rank never happens, and the new item waits behind a quiet "1 new item: show" pill until the editor shows it

  Scenario: The captured record reads the curation card first, with extracted text as a fallback
    Given References with a ready curation card, a failed one, a failed one beside older extracted text, a degraded one that may be paywalled, and one still running
    When the editor opens each of them
    Then the record shows the card's status, word count, summary, GROBID fields and the curation text, and the card badge follows the curation status
    And "No text captured" shows only when neither a card with text nor extracted text exists, with the card's typed reason in words
    And a paywall phrase at the end of a long capture says it may be cut off, and a degraded card says a stage is unfinished
    And a long capture that only ends without a full stop lists that as a fact but is not sent to the editor as a capture check

  Scenario: An editor pastes or corrects the text and says whether the capture was complete
    Given a Reference with no captured text
    When the editor chooses Paste or correct the text, pastes the article and marks the capture complete
    Then correctReferenceCapture receives the text and the verdict, the record shows the new text and the verdict, and the summary is marked as awaiting the next run
    And a verdict alone is saved as just a label, and nothing can be saved without a verdict

  Scenario: On a phone, a swipe anywhere in the detail scrolls the page, never a box inside it
    Given References where one has full stored text, one only a teaser, and one nothing but its link
    When the editor opens the full-text one at 375 pixels and shows all of the captured text
    Then the captured text and every text box grow to fit their text, none of them scrolls inside itself, and the page scrolls past them

  Scenario: The newsroom asks a source page whether it may be framed before it shows a live preview
    Given a source page and the headers it sends
    When the newsroom checks whether it may show that page in a frame
    Then a page that sends X-Frame-Options or a frame-ancestors rule that does not allow every site is not framed, and one with neither rule is
    And only public web addresses on the standard ports are ever fetched, so the check cannot be pointed at the server's own network
