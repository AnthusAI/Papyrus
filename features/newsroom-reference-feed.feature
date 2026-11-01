@brand-agnostic @reference-feed-fixtures
Feature: The References page is a news feed ranked by what the Cyclotron expects the editor to accept
  References open as a feed in a responsive grid, like a news app: a larger lead card, then cards with a picture, a title, a one-line
  dek, the source and its age, the Cyclotron's prediction (Accept or Reject with its confidence and an icon) and the editor's own
  Accept and Reject. The feed is one list with two choices, each a pair of buttons with an icon and words, never a drop-down and never
  tabs. Sort is Best bets, the default, or Newest. Best bets is the Cyclotron's own confidence that the editor will Accept, highest
  first, whatever the age: the items it expects the editor to Accept most surely come first, the items with no prediction sit in the
  middle, and the strongest predicted Rejects come last. Newest is the latest arrival first. Show is Unrated only, the default, or
  Include rated, which adds the References that already have a human answer to the same list in the same sort, each showing its
  recorded vote. Both choices are remembered in this browser. Nothing is hidden because it is old. A card the editor rates stays where
  it is for the rest of the visit, showing the answer and whether the Cyclotron matched it, and the order is taken once per visit in
  either sort. The page shows its shell and card skeletons at once instead of a checking screen, and a return visit shows the last
  saved cards while the live read runs. These scenarios use synthetic References in an isolated browser at 375 and 1440 pixels and
  never touch production.

  Scenario: The strongest predictions are first and the strongest Rejects are last
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then the order runs from the strongest Accept, through the item with no prediction, to the strongest Reject
    And the first card is the large lead card, and the grid has one column on a phone and three or more on a desktop
    And every card shows its title, dek, source, age, the Cyclotron's Accept or Reject with its confidence and icon, and large Accept and Reject buttons
    And a title shows without the site name a page tacks on its end, such as " | Brookings" or " | Poverty and Development | Al Jazeera"
    And nothing scrolls sideways and there are no drop-downs

  Scenario: Best bets goes by the Cyclotron's original confidence, whatever the age
    Given References of very different ages with predictions
    When the feed is ranked
    Then an old strong Accept still ranks above a new weaker one, and an old Reject never rises above a new Accept
    And ties go to the newest item and then to a stable order
    And a card rated this visit does not move any other card

  Scenario: A rated card stays in place and shows whether the Cyclotron matched, and Unrated only leaves it out on the next visit
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor accepts a card, then rejects it with a written reason, and rejects a card that was predicted Reject
    Then each rated card stays in its place and shows Saved
    And the answered button says Confirmed or Overturned, in words and a marker as well as colour
    And Rejecting asks for a written reason in words and changes nothing until one is given
    And while an answer is being saved the button says Sending, or Updating when it changes a saved answer, and never says it is unrecorded
    And choosing Include rated keeps the answered cards where they were

  Scenario: The decision is one control: a prediction above one pair of buttons, with the reason under them
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then the prediction bar, the Accept and Reject buttons and the reason field are all the same width, on a card and in the review card, at 375 and 1440 pixels
    And there is no second row of prediction cells: the predicted side is marked on the button itself
    And the confidence bar is centred at 50%, filling toward Accept for an Accept-leaning prediction and toward Reject for a Reject-leaning one
    And the fill's length is the prediction's distance from 50% doubled, and with no prediction the bar is empty and says No prediction
    And the confidence is printed in the bar and on no button, moving beside the fill when the fill is too short to hold it
    And before an answer the predicted button carries its own tone and says Predicted, with no border anywhere

  Scenario: After an answer the prediction's own marker and bar carry the verdict, and the answer stays neutral
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor answers with the predicted side and against it
    Then the chosen button says Confirmed when it agrees with the prediction and Overturned when it does not
    And the marker on the predicted side and the confidence bar turn green for a confirmation and red for an overturn
    And the chosen button itself is never tinted by the verdict: it is the same fill either way
    And the chosen button is filled and the other is quiet, and tapping the chosen one does not unselect it

  Scenario: An old unrated item stays in the one list, and can still be rated
    Given an old unrated Reference with a strong prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then it stays in the one list where its original confidence puts it, and last when sorted by Newest, with no Earlier section and no tabs
    And an old card can be rated and stays where it is

  Scenario: Best bets is the default, Newest sorts by date, and Unrated only is the default
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then Best bets and Unrated only are pressed, and each choice is a pair of buttons with an icon and words
    And choosing Newest orders the cards by arrival, newest first, whatever the predictions say

  Scenario: Include rated adds the answered cards with their votes, and both choices are remembered
    Given a feed with References that were accepted automatically or by an editor
    When the editor chooses Include rated and reloads the page
    Then the answered cards join the same list in the active sort, each showing its recorded vote
    And the page remembers Newest and Include rated for this browser, with no tabs on the page

  Scenario: The feed is flat, rounded and borderless, one list in rank order
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then no card, button, pill, chip, panel or skeleton has a border, an outline or a rule, and surfaces differ only by tone
    And cards are rounded rectangles with a full-bleed picture across the top, and pills are fully rounded
    And the feed is one list in rank order with no section headings, the predicted Rejects last
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
    And it falls back to the site's favicon.ico only when that is more than an empty placeholder
    And only real host names that resolve to public addresses are ever fetched

  Scenario: The page shows its shell and card skeletons at once, never a checking screen
    Given the References are still loading
    When the editor opens the feed at 375 and 1440 pixels
    Then the page header, the sort and show buttons and card skeletons are on screen and no text says it is checking credentials

  Scenario: A return visit shows the last saved cards, read only, until the live read arrives
    Given this browser saved the last feed it showed
    When the editor opens the References page while the session is still being confirmed
    Then the saved cards are shown at once with a note that they are the last view
    And answering is switched off with the reason in words, and a saved copy never answers on its own
    And the saved copy and the session summary expire, survive a blocked or full browser store, and are wiped on sign-out

  Scenario: A Reference accepted automatically, by the Cyclotron or by a monitor's rule, says so, in words and an icon, apart from an editor's accept
    Given a Reference the Cyclotron accepted automatically, one a monitor's rule accepted, and another that an editor accepted
    When the editor chooses Include rated at 375 and 1440 pixels
    Then the automatically accepted card says Accepted automatically with a Lucide icon, one accepted by a monitor's rule says so too, and the editor's accept carries no such mark
    And both read as accepted, and the editor can still change either

  Scenario: The ranking is explained in plain words with this site's own numbers
    Given the feed is open
    When the editor opens how this feed is ranked
    Then it explains Best bets, Newest, Unrated only, Include rated and why a rated card stays put
    And it says that age does not change the order

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
    Then the grid scrolls smoothly so the selected card stays in view, on a tinted surface with a thick ring drawn outside it on every side, which takes no space in the grid and is never cut off at the feed's edge
    And opening a card from the grid selects it too
    And before any card is selected there is no Detail pane and the feed has the whole width

  Scenario: The Previous and Next bar stays in view at the bottom of the detail while the reference scrolls
    The detail of a long reference scrolls, but the bar with Previous, the position and Next does not go with it. On a phone the
    bar sits just above the bottom tab bar, which has its own safe-area padding; from the tablet width up it sits at the bottom of the
    detail pane beside the feed. It has a solid tone of its own, so the text never shows through it, and the end of the content is
    never hidden behind it.
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens a long reference and scrolls its detail to the bottom at 375, 390 and 1440 pixels
    Then the Previous and Next buttons are still in view, above the tab bar on a phone and at the bottom of the detail pane on a desktop
    And the bar is in the same place at the top, part way down and at the bottom of the detail
    And the last of the detail's content ends above the bar, so nothing is covered by it

  Scenario: Selecting a reference by any means opens its detail at the top with the headline in view
    A reference opened from a card, with Next, with Previous or by the keyboard shortcuts for them, from a link, or as the item after
    a vote always shows its headline first, wherever the previous reference was scrolled to. The page resets the scroller that really
    scrolls: the detail pane's own from the tablet width up, and the newsroom's page scroller on a phone. Showing the same
    reference again, as a background refresh does, leaves the editor's place alone.
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor scrolls a long reference to the bottom and then selects another with a card, with Next and with Previous
    Then each newly selected reference is scrolled to the top and its headline is in view above the bar, on a phone and on a desktop
    And a refresh of the reference that stays open does not move its scroll position

  Scenario: The grid stays put while the editor selects, rates and the data refreshes
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor selects five items in turn, rates two, and a background refresh changes the predictions and adds a new item
    Then every card keeps its order and its position and size, and the grid does not scroll, at 375, 900 and 1440 pixels
    And the column count stays fixed while the detail pane is open: from the tablet width up the pane appears beside the grid with the first selection and then holds its place, so moving between items moves nothing, while below that the detail is a sheet
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

  Scenario: An editor uploads the PDF they downloaded when the source sits behind a bot wall
    Given a Reference with no captured text
    When the editor chooses Upload a PDF, marks the capture incomplete and chooses a PDF, at 375 and 1440 pixels
    Then the PDF is stored as an attachment of the Reference, correctReferenceCapture receives its id and the verdict, and the record shows the new text with the line "Text from a PDF you uploaded"
    And a refusal from the server and a failed upload each show in words, and no upload button appears without the correction action

  Scenario: On a phone, a swipe anywhere in the detail scrolls the page, never a box inside it
    Given References where one has full stored text, one only a teaser, and one nothing but its link
    When the editor opens the full-text one at 375 pixels and shows all of the captured text
    Then the captured text and every text box grow to fit their text, none of them scrolls inside itself, and the page scrolls past them

  Scenario: The newsroom asks a source page whether it may be framed before it shows a live preview
    Given a source page and the headers it sends
    When the newsroom checks whether it may show that page in a frame
    Then a page that sends X-Frame-Options or a frame-ancestors rule that does not allow every site is not framed, and one with neither rule is
    And only public web addresses on the standard ports are ever fetched, so the check cannot be pointed at the server's own network

  Scenario: The feed holds every Reference, not just the first page the backend returns
    Given a newsroom with more References than one page of the backend's list holds
    When the editor opens the References feed
    Then the feed reads page after page until the backend says there are no more
    And each Reference appears once even when two pages overlap
    And a page token that repeats stops the read with a message instead of looping

  # Predictions are read for the References the feed shows, one indexed read each, never from the newsroom's whole relation feed. A
  # Shipped-sized newsroom holds about 16,000 relations and more arrive every time a monitor runs, so any fixed number of pages would
  # one day be too few and the feed would fail. The cost follows what is on screen, so the feed keeps working however much the newsroom holds.
  Scenario: A newsroom with more relations than any page budget still shows predictions for the visible References
    Given a newsroom with 60 References and 20,000 relation records, more than any fixed page budget could read
    When the editor opens the feed
    Then predictions are read for the 24 References on the first page, one read each, and for no other Reference
    And every one of those cards shows its prediction and confidence
    And nothing says that predictions are unavailable or that the activity feed is incomplete
    And scrolling to the end reads the next page's predictions only, and its cards join after the first page without moving it

  Scenario: One Reference's prediction failing shows on that card alone
    Given a feed where the prediction read for one Reference is refused
    When the feed has loaded
    Then that card says Prediction unavailable and offers Retry, in words and an icon
    And every other card shows its prediction, and no message about predictions appears for the page
    And choosing Retry reads that one prediction again and the card shows it

  Scenario: The cards render without predictions when every prediction read fails
    Given a feed where every prediction read is refused
    When the feed has loaded
    Then every Reference still shows its title, source, age and its Accept and Reject buttons
    And each card says Prediction unavailable with Retry, and the feed is never left as grey skeletons
    And the order is the server's own, newest first, because nothing can rank them yet

  Scenario: The unit rules behind the paged predictions
    Given a newsroom with about 16,000 relations held by subject
    When the feed windows its References and reads their predictions
    Then only the shown References are read, at most a few reads are in flight at once, and one failing read fails only its own Reference
    And the window is the newest pages of unanswered items plus the answered ones that arrived since, and it only ever grows
    And a later page is ranked after everything already placed, while a new arrival waits behind the new-items pill
