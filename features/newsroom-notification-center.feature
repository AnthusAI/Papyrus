@brand-agnostic @notification-center-fixtures
Feature: The Notification Center answers "What needs me?" with one feed that mixes everything that may need a person
  The console home is a single feed in the style of the References feed: flat tones and rounded cards, no borders or lines. It mixes
  References, batches of generated story ideas, story reviews, held email, captures that may be cut off, and flags. Hard gates come first. After them the
  order is the value of the editor's input: how unsure the Cyclotron is, times how much the item matters, with no change for age, and with
  no more than two items of one type in a row while another type waits. The order is taken once when the editor arrives and then left
  alone. Pills narrow the feed to one type and count what waits. Items the Cyclotron is confident about do not ask for the editor;
  they wait under "Decided automatically", where they can be overruled. Every card but a batch of ideas has the References feed's Accept and Reject grid: ideas are decided on the Stories board, where moving an idea forward accepts it and moving it to Spiked with a reason declines it, so a batch is ONE card that links to the Idea column. A card opens the same detail pane whatever its type, with a body that fits it. Ignoring an item decides nothing: each card says
  what happens if it is left alone. A slim strip says how much the editor has shaped the feed this week. These scenarios use synthetic
  data in an isolated browser, at 375 and 1440 pixels, and never touch production.

  Scenario: A morning batch of generated ideas is one card that links to the Idea column
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor opens the Notification Center at 375 and 1440 pixels
    Then the batch is one card that names the run's three ideas, says they wait in the Idea column and links to the Stories board, with no Accept or Reject and no prediction row
    And the header counts the batch, nothing scrolls sideways, no card has a border, and the retired Approve, Steer and Agree wording and the words Proposed Story are gone
    And opening the batch lists each idea with its stage, links each idea to its story and the card to the Idea column, and has no decision panel and no Why box

  Scenario: Accepting is moving an idea forward, declining is spiking it, and a finished batch leaves the feed
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor looks at a batch of which one idea was moved forward and one was spiked on the board, and at a batch whose ideas have all left the Idea column, and at a batch raised before ideas were stories
    Then the card says how many of its ideas still wait in the Idea column, a batch with none left has no card, a batch that names no story has no card, and looking decides nothing

  Scenario: References keep their prediction and the pills narrow the feed
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor looks at pending References and uses the Ideas and References pills at 375 and 1440 pixels
    Then each Reference card marks the predicted Accept or Reject with its confidence, or says there is no prediction
    And a card opens the same detail pane the References page has, a rating is saved through the References review, and an empty pill says so

  Scenario: Hard gates come first, types are mixed, and the pills count and filter
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor opens a feed that mixes a hard gate, a batch of ideas, References and a held email at 375 and 1440 pixels
    Then the hard gate is the first card and says it is a hard gate, and no third card of one type follows two of the same while another type waits
    And the pills count what waits for each type and a pill narrows the feed to that one type

  Scenario: Confident items wait under Decided automatically and can be overruled
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor has confirmed ten of the Cyclotron's predictions and a Reference arrives that it is very sure about
    Then that Reference is not in the feed, it is listed under Decided automatically with an Overrule button, and the "You're shaping this" strip counts the week's decisions and agreements

  Scenario: The same detail pane opens for every type
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor opens a hard gate, a batch of ideas, a held email and a Reference
    Then each opens in the one detail pane with a body that fits its type, a held email's text is inert and its links are not clickable, and a Reference shows our captured record
    And before anything is selected there is no Detail pane and the feed has the whole width

  Scenario: The open item is in the address, so it can be linked and reopened
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor opens a Reference, and later follows a link to it, and a link to an item that is no longer waiting
    Then opening an item shows its needs-me address with its id, and closing it on a phone returns the address to the overview
    And a link to an item opens the feed with that item in the detail pane, on a desktop and on a phone
    And a link to an item that is not waiting any more says so, with no empty pane
    And signing in from a deep link comes back to that link, not to the overview

  Scenario: Ignoring an item leaves the default
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor opens and reads items without deciding them
    Then nothing is moved, answered, rated or decided, and each card says what happens if it is left alone

  Scenario: A held email is decided with the same Accept and Reject
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor rejects a held email with a Why written in its detail pane
    Then the email is rejected with that reason, its card shows the answer, and nothing else is changed

  Scenario: A reason that cannot be saved is said in words and never lost
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor writes a note after answering a hard gate and the save is refused
    Then the page says in words that the note could not be saved and is kept, the typed text stays in the box, and tapping away saves it

  Scenario: A stage review, a hard gate and a flag take their note in either order
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor answers a hard gate and then writes its note, and writes a flag's note before acknowledging it and changes it afterwards
    Then each note is saved onto the existing answer, the choice and the person who answered stay as they were, and the card shows the note

  Scenario: A held email and a Reference take their reason in either order
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor rejects a held email and then writes its reason, and accepts a Reference and then writes its reason
    Then the held email's decision is sent again with the reason so the recorded reason changes, the Reference's rating is saved again with its note, and each reopens showing its reason

  Scenario: Previous and Next stay in the bottom-right corner of the screen
    Given an isolated Notification Center with a batch of three generated ideas
    When the editor opens a hard gate at 1440 by 900, 1440 by 1300 and 1024 by 768 and scrolls the page and the feed, and again on a phone
    Then the Previous and Next bar's bottom-right corner is the viewport's bottom-right corner, other sections below the feed never push it up, and on a phone it is the fixed bottom of the sheet

  Scenario: While the session is checked, the page shows the feed's own skeleton, not an older outlined one
    Given the newsroom is still checking the editor's session
    When the Notification Center or another newsroom page is loading
    Then the loading state is the feed's skeleton of flat tones and rounded cards, with no border, outline or rule
    And when the feed loads it replaces the skeleton in place, in the same shapes

  Scenario: The board's loading columns are flat and rounded too, never the old outlined boxes
    Given the newsroom is still checking the editor's session
    When the editor opens the board and its records are still loading
    Then the board shows three columns of pulsing cards in flat tones and rounded rectangles, with no border, outline or rule

  Scenario: The newsroom's own bar and menus are flat, and a phone's bar has nothing cut off
    Given the newsroom shell at 375 and 1440 pixels
    When the editor looks at the top bar, the sidebar, the account button and the bottom navigation
    Then none of them has a border, an outline or a rule, and the controls are tone fills in rounded rectangles
    And the bar has one search field and no second search button
    And on a phone the bar shows the search field and the account button only, with no cut-off page title, because the page's own heading names it and Settings is in the account menu
