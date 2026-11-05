Feature: Share a Story by URL
  An editor shows a Story in progress, in the website's real public layout and clearly labelled DRAFT, to people who have no newsroom sign-in.
  The editor makes a link and chooses who can open it (anyone with the link, or only people signed in to the newsroom as editors or admins),
  what it shows (the Story's current version, which follows new versions, or one version only) and how long it lasts (7, 30 or 90 days,
  30 unless chosen; there is no link that never expires). The token is 256 random bits, shown once and kept only as a hash. A link that is
  unknown, expired, revoked or ended says the same plain thing, so a stranger cannot tell which. The page is drawn on demand into the
  response with the site's own page renderer, so nothing is written to the live site, and no link shows up on any listing, feed or sitemap.
  These scenarios run the real code against an in-memory stand-in for the data API and a fixture site.

  Background:
    Given a site with a published Story and an editor
    And a draft Story "Lower fords" that is not published

  Scenario: A stranger opens a shared draft in the public layout, labelled DRAFT
    Given the editor shares the draft with anyone with the link
    When a stranger opens the link
    Then the page is the site's own public layout with the draft's text
    And the page carries a DRAFT band with an icon and the word DRAFT
    And the page title starts with "DRAFT: "
    And the page asks not to be indexed and has no canonical address, analytics or consent banner

  Scenario: A link for signed-in people sends a stranger to sign in and turns away someone without editor rights
    Given the editor shares the draft with only people signed in to the newsroom
    When a stranger opens the link
    Then they are sent to sign in
    When a signed-in reader without editor rights opens the link
    Then they are told the link is not available
    When a signed-in editor opens the link
    Then the page is the site's own public layout with the draft's text

  Scenario: The current version follows new versions and a pinned version stays put
    Given the editor shares the current version, and also shares version 1 only
    When the editor saves a second version
    Then the link for the current version shows the second version
    And the link for version 1 still shows the first version only

  Scenario: Expiry is a choice of 7, 30 or 90 days and never is not on offer
    When the editor makes links lasting 7, 30 and 90 days
    Then each link ends exactly that many days after it was made
    And a link with no expiry choice lasts 30 days
    And a link that lasts 365 days or forever is refused

  Scenario: Unknown, expired and revoked links are indistinguishable
    Given the editor shares the draft with anyone with the link
    When the editor revokes it
    And a link was made that has since expired
    Then the revoked link, the expired link and a link that never existed all give the same plain answer

  Scenario: Publishing the Story ends its links and the old address points at the published page
    Given the editor shares the draft with anyone with the link
    When the Story that was shared is published
    Then the old link shows a plain page that links to the published address
    And the draft text is not in that answer

  Scenario: Spiking the Story ends its links
    Given the editor shares the draft with anyone with the link
    When the Story that was shared is spiked
    Then the old link gives the plain "not available" answer

  Scenario: Pictures load through the link and reach nothing else
    Given the draft has a picture and another Story has a picture of its own
    And the editor shares the draft with anyone with the link
    When a stranger asks the link for the draft's picture
    Then the picture is found
    When a stranger asks the link for the other Story's picture, a parent path, an encoded path or another host
    Then every one of them gets the plain "not available" answer

  Scenario: Only editors and admins can make, list or revoke links
    When a reader without editor rights tries to share the draft
    Then it is refused and no link exists
    When a stranger with no sign-in tries to list or revoke links
    Then it is refused too

  Scenario: Making, opening and revoking are recorded on the Story without personal data
    Given the editor shares the draft with anyone with the link
    When a stranger opens the link twice on the same day
    And the editor revokes it
    Then the Story's record shows the link was made, opened that day and revoked
    And the record names no address, agent or identity for the stranger
    And the editor's list shows who made the link, who can view, what it shows, when it expires and when it was last opened but never the token

  Scenario: A shared draft is never written to the site or listed on it
    Given the editor shares the draft with anyone with the link
    When a stranger opens the link
    Then nothing was written to the live site's output
    And no page, listing, feed or sitemap of the site mentions the draft or the link

  Scenario: The page shows nothing from the newsroom's private working
    Given the draft has an editorial note, a review request, a message and a star rating
    And the editor shares the draft with anyone with the link
    When a stranger opens the link
    Then none of those appear in the page and none were read to make it

  Scenario: The command line makes, lists and revokes links
    When an editor runs "stories share --story <lineage> --signed-in --expires 7 --version 2" while signed in
    Then the newsroom is asked for a signed-in link on version 2 lasting 7 days and the URL is printed once
    When an editor runs "stories share --story <lineage> --expires 365"
    Then the command is refused before the newsroom is asked
    When an editor runs "stories share --story <lineage> --dry-run"
    Then the newsroom is not asked
