Feature: The home-page stylesheet is linked only where it is used
  A site that sets homePage gets css/papyrus-home-page.css, the stylesheet for Reference and thread cards. Only a page that places
  one of those includes links it, and the link carries a version token of its own, a short hash of that one file. Every other page
  keeps the site-wide version token, which leaves the home-page stylesheet out of its input. So turning homePage on, or editing
  that stylesheet, changes no byte of a page that places no card, and a site that adopts the feature does not see its whole
  cache turn over. The file is still published to css/ whenever homePage is set.

  Scenario: A page without home-page includes is byte-identical with and without the homePage setting
    The same site is projected twice, once with homePage and once without. Neither places a card.
    Given the home-page fixture site with only its quiet page is projected with homePage set
    And the same site is projected without homePage
    Then "quiet/index.html" is identical in both projections
    And "index.html" is identical in both projections
    And the page "quiet/index.html" has no home-page stylesheet link
    And the stylesheet "css/papyrus-home-page.css" is published in the first projection only

  Scenario: A page with a references include links papyrus-home-page.css with its own version token
    Given the home-page fixture site is projected
    Then the page "front/index.html" links the home-page stylesheet with the first 12 hex characters of that file's SHA-256 as its version
    And the page "quiet/index.html" has no home-page stylesheet link

  Scenario: Changing the home-page stylesheet does not change the version token of other pages
    Given the home-page fixture site with only its quiet page is projected with homePage set
    And the home-page stylesheet is edited and the site is projected again
    Then "quiet/index.html" is identical in both projections
