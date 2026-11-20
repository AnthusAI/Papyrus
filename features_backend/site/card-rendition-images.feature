Feature: Cards show the same picture as the article page
  A story's front matter names its card picture by the path the picture was stored under (assets/<slug>/<file>).
  The file at that path is the original upload. It exists in the site only when the site keeps originals
  (media.originals) and the upload was announced after it began to, and only for the exact path the story holds; a
  story saved again with its pictures numbered (chart.png became chart-2.png) can name a path the site never held.
  The responsive renditions of the picture exist whenever it was uploaded at all, and they are what the article page
  shows. A card, a list, the home page and a hero are drawn from the same page rendering, so every <img> on a page
  whose address is a stored picture with renditions points at the rendition the article page uses. A missing original
  can never leave a coverless card. A picture with no renditions, a web address, the social image tags, the feeds and
  the generated data are left exactly as written, and a site under a base path gets base-path addresses.

  Scenario: A card names the rendition the article page shows, not the original
    Given a site with images whose story "hello" names the card picture "chart.png" and the Night picture "chart.dark.png"
    And the story's pictures are uploaded
    When the cards are rendered from the site store
    Then the card on the front page shows the Day picture of the article page
    And the card on the front page shows the Night picture of the article page
    And no card names the original file "chart.png"

  Scenario: The card still shows the picture when the original is not in the site
    Given a site with images whose story "hello" names the card picture "chart.png" and the Night picture "chart.dark.png"
    And the story's pictures are uploaded
    And the site holds no original files
    When the cards are rendered from the site store
    Then the card on the front page shows the Day picture of the article page
    And that picture is a file of the site store

  Scenario: A site under a base path gets base-path addresses
    Given a site under the base path "/articles" with images whose story "hello" names the card picture "chart.png"
    And the story's pictures are uploaded
    When the cards are rendered from the site store
    Then the card on the front page shows an address starting with "/articles/assets/responsive/"

  Scenario: A card picture without renditions and a web picture are left as written
    Given a site with images whose story "hello" names the card picture "/assets/draft-unsectioned-a1b2c3d4/missing.png"
    And the story's pictures are uploaded
    When the cards are rendered from the site store
    Then the card on the front page shows "/assets/draft-unsectioned-a1b2c3d4/missing.png"

  Scenario: The social image still names the story's own picture
    Given a site with images whose story "hello" names the card picture "chart.png" and the Night picture "chart.dark.png"
    And the story's pictures are uploaded
    When the cards are rendered from the site store
    Then the social image of the story page names "chart.png" and not a rendition
