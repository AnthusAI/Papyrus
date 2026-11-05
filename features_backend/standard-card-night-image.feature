Feature: A story card shows the Night picture when its figure has a Day and Night pair
  A Story whose figure has a Day and a Night picture names both in its front matter, as image and imageDark. On every site that
  uses the standard listing cards, the card carries both pictures and the reader's theme decides which one shows: the system
  setting, or the theme the reader picked by hand. This needs no script, so a static page works without JavaScript. A browser
  does not fetch the picture that is hidden. A card whose figure has no Night picture is exactly as it was, and the picture
  that social networks, feeds and the site's public data use is always the Day one.

  Scenario: A card whose figure has a Night picture carries both pictures
    Given a Story whose figure has the Day picture "/media/fig.png" and the Night picture "/media/fig.dark.png"
    When the listing page is projected
    Then the card has a Day picture "/media/fig.png" and a Night picture "/media/fig.dark.png"

  Scenario: A card whose figure has only a Day picture is unchanged
    Given a Story whose figure has only the Day picture "/media/fig.png"
    When the listing page is projected
    Then the card has the single picture "/media/fig.png" and no Night picture

  Scenario: Social images and generated data keep the Day picture
    Given a Story whose figure has the Day picture "/media/fig.png" and the Night picture "/media/fig.dark.png"
    When the listing page is projected
    Then no social image tag, feed or data file names the Night picture

  Scenario: The stylesheet follows the system setting and a theme picked by hand
    When the shared components stylesheet is read
    Then the Night picture shows when the system is dark unless the reader picked Light by hand
    And the Night picture shows when the reader picked Dark by hand, whatever the system says
