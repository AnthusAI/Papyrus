Feature: A page places Reference cards from the home-page snapshot with ::include{kind="references"}
  A Papyrus site can show part of its curation to visitors. The home-page snapshot (_data/home-page/references.json) holds the
  accepted References and the ones the Cyclotron recommends but an editor has not yet accepted. An authored page places them with
  ::include{kind="references" select="recent|confident|recommended"}. The grids are rendered at projection time, so they work with
  no script and the Markdown twin of the page keeps the include line as written for agents to read.

  Three selections draw from the snapshot: recent (accepted, newest accepted first), confident (accepted, highest Cyclotron
  confidence first) and recommended (not yet accepted, highest confidence first). Components on one page share a ledger: the first
  component to place a Reference keeps it, and a later component refills up to its count from its own ordering. Nothing is shared
  between pages. A card shows Cyclotron's confidence as a number with a label, an icon and a meter drawn by shape, and a
  recommended Reference says so in words and an icon. Cards use flat tones and rounded rectangles, with no borders.

  Scenario: A page places the six most recently accepted References as tiles
    A grid with no count of its own uses homePage.references.defaultCount, which is 6.
    Given the home-page fixture site is projected
    Then the "recent" grid on "defaults/index.html" lists "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact"
    And every card in the "recent" grid on "defaults/index.html" is a tile

  Scenario: A grid with no count of its own uses the configured default count
    Given the home-page fixture site is projected with a default count of 2
    Then the "recent" grid on "defaults/index.html" lists "Accepted eight", "Accepted seven"

  Scenario: A page ranks accepted References by Cyclotron confidence
    Two References with the same confidence are ordered by the newest arrival.
    Given the home-page fixture site is projected
    Then the "confident" grid on "ranked/index.html" lists "Accepted eight", "Accepted two", "Accepted four", "Accepted seven", "Accepted five", "Accepted six", "Accepted one", "Accepted three, contact"

  Scenario: A page shows recommended References labelled as not yet accepted, in text and icon
    Given the home-page fixture site is projected
    Then the "recommended" grid on "recommended/index.html" lists "Pending high", "Pending mid", "Pending unrecorded confidence", "Pending undecided"
    And every card in the "recommended" grid on "recommended/index.html" says "Recommended by Cyclotron, not yet accepted" next to a "sparkles" icon
    And no card in the "recent" grid on "front/index.html" says "not yet accepted"

  Scenario: Three components on one page never repeat a Reference; the first component wins
    Given the home-page fixture site is projected
    Then the "recent" grid on "front/index.html" lists "Accepted eight", "Accepted seven", "Accepted six"
    And the "confident" grid on "front/index.html" lists "Accepted two", "Accepted four", "Accepted five"
    And the "recommended" grid on "front/index.html" lists "Pending high", "Pending mid"
    And no Reference title appears twice on "front/index.html"

  Scenario: A later component refills to its count from its own ordering after skipping
    The most confident Reference, "Accepted eight", is already placed by the first component, and so is "Accepted seven". The
    second component skips them and still shows three cards, taking the next ones in its own order.
    Given the home-page fixture site is projected
    Then the "confident" grid on "front/index.html" has 3 cards
    And the "confident" grid on "front/index.html" does not list "Accepted eight", "Accepted seven", "Accepted six"

  Scenario: De-duplication is per page and never across pages
    Given the home-page fixture site is projected
    Then the "recent" grid on "front/index.html" lists "Accepted eight", "Accepted seven", "Accepted six"
    And the "recent" grid on "defaults/index.html" lists "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact"

  Scenario: A section attribute keeps only that section's References
    A component with nothing left shows its empty text when it has one.
    Given the home-page fixture site is projected
    Then the "recent" grid on "tools/index.html" lists "Accepted eight", "Accepted four"
    And every card in the "recent" grid on "tools/index.html" is a row
    And "tools/index.html" shows the text "No recommendations in this section."

  Scenario: A Story listing and Reference grids interleave in document order on one authored page
    Given the home-page fixture site is projected
    Then "mixed/index.html" shows these in document order: "Fungi Underground", "A Closer Look at Moss", "Two recent", "Ferns in Winter", "Two confident"
    And the "confident" grid on "mixed/index.html" lists "Accepted two", "Accepted four"

  Scenario: The Markdown twin keeps the references include line as written
    Given the home-page fixture site is projected
    Then "front/index.md" contains the line '::include{kind="references" select="recent" count="3" heading="Recently accepted" more="/tools/"}'
    And "front/index.md" contains the line '::include{kind="references" select="confident" count="3" heading="Most confident"}'
    And "front/index.md" contains the line '::include{kind="references" select="recommended" count="2" heading="Recommended by Cyclotron"}'
    And "front/index.md" does not contain "home-page-tile"

  Scenario: A references include on a site without homePage configured fails the build naming the file
    Given the home-page fixture site is projected without a homePage setting
    Then the build failed saying "pages/front.md" and "homePage is not configured in projection.json"

  Scenario: An empty snapshot renders no grid and the page still builds
    Given the home-page fixture site is projected with an empty snapshot
    Then "front/index.html" has no Reference grid
    And "tools/index.html" shows the text "Nothing here yet."
    And "front/index.md" contains the line '::include{kind="references" select="recent" count="3" heading="Recently accepted" more="/tools/"}'

  Scenario: A site that has not written a snapshot yet renders no grid and the page still builds
    Given the home-page fixture site is projected with no snapshot file
    Then "defaults/index.html" has no Reference grid

  Scenario: Reference cards show confidence as text, icon and meter shape, and have no borders and show state in text and icon, not colour alone
    Given the home-page fixture site is projected
    Then the card for "Accepted two" shows "93% confidence" next to a "gauge" icon and a meter with 5 filled segments
    And the card for "Accepted seven" shows "70% confidence" next to a "gauge" icon and a meter with 4 filled segments
    And the card for "Accepted six" shows "50% confidence" next to a "gauge" icon and a meter with 3 filled segments
    And the card for "Accepted three, contact" shows "10% confidence" next to a "gauge" icon and a meter with 1 filled segments
    And the unfilled meter segments of a card are outlined shapes, not only a lighter colour
    And the home-page stylesheet draws no borders or lines
    And the card for "Accepted eight" says it was accepted by an editor
    And the card for "Accepted six" says it was accepted automatically

  Scenario: A row card shows Cyclotron's confidence compactly, with a label and never colour alone
    Given the home-page fixture site is projected
    Then the row card for "Accepted two" shows "93%" with a visually hidden "confidence" label, a "gauge" icon and a meter with 5 filled segments
    And the row card for "Accepted four" shows "80%" with a visually hidden "confidence" label, a "gauge" icon and a meter with 4 filled segments

  Scenario: A recommended row shows both the recommended label and the confidence
    Given the home-page fixture site is projected
    Then the row card for "Pending high" shows the label "Recommended by Cyclotron, not yet accepted" and "92%"

  Scenario: The rendered pages hold no email, person id, Cognito sub or UUID
    Given the home-page fixture site is projected
    Then the identity scanner finds nothing in any rendered page

  Scenario: Cards link only to safe addresses
    Given the home-page fixture site is projected with a Reference whose address is "javascript:alert(1)"
    Then no page links to "javascript:"

  Scenario Outline: A page path, section base or collection base equal to a reserved prefix fails the build
    Newsroom is also reserved on sites whose edge routes the CMS; projection cannot see the edge, so the message says so.
    Given a projection.json that sets <setting> to "<segment>"
    When the standard settings are read
    Then reading fails saying "<setting>" and "is reserved" and "newsroom"

    Examples:
      | setting                 | segment |
      | pages.path              | api     |
      | urls.sections.docs.base | api     |
      | collections.docs.base   | api     |

  Scenario: Other page paths are not reserved
    Given a projection.json that sets pages.path to "newsroom-notes"
    When the standard settings are read
    Then the settings are accepted
