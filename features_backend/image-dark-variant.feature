Feature: Images with a dark variant
  An article figure can carry a second, dark-mode picture. The author writes
  srcDark on the image directive, or uploads a file named like the light one
  with ".dark" before the extension. The dark picture goes through the same
  responsive pipeline as the light one. Both variants are in the page; stock CSS
  shows one of them. The site's theme toggle wins when it sets data-theme on
  the root element; with none set, the reader's operating system preference
  decides. The hidden variant is lazy, so it is not downloaded when not shown.
  The light picture fixes the figure's width and height, so switching theme
  never moves the page. A pair that cannot work stops the build and names the
  image.

  Scenario: A pair renders both variants
    Given an image pair "images/chart.png" of 800 by 600 pixels, and a dark file "images/chart-night.png" of 800 by 600 pixels
    When I render the image "images/chart.png" with srcDark "images/chart-night.png"
    Then the figure has a light variant and a dark variant
    And both variants have responsive renditions of their own file
    And the light image keeps width 800 and height 600
    And the dark image is lazy loaded

  Scenario: The operating system dark preference picks the dark variant
    Given an image pair "images/chart.png" of 800 by 600 pixels, and a dark file "images/chart-night.png" of 800 by 600 pixels
    When I render the image "images/chart.png" with srcDark "images/chart-night.png"
    Then when the root has no theme set, a dark operating system preference hides the light variant and shows the dark one

  Scenario: The site theme attribute overrides the operating system
    Given an image pair "images/chart.png" of 800 by 600 pixels, and a dark file "images/chart-night.png" of 800 by 600 pixels
    When I render the image "images/chart.png" with srcDark "images/chart-night.png"
    Then data-theme "dark" on the root shows the dark variant whatever the operating system prefers
    And data-theme "light" on the root keeps the light variant even when the operating system is dark
    And a dark class on the root is understood when no data-theme is set

  Scenario: A dark file named next to the light one is paired automatically
    Given an image pair "images/figure.png" of 800 by 600 pixels, and a dark file "images/figure.dark.png" of 800 by 600 pixels
    When I render the directive image "images/figure.png" without srcDark
    Then the figure has a light variant and a dark variant

  Scenario: An image with no dark file renders as before
    Given an image "images/plain.png" of 800 by 600 pixels
    When I render the directive image "images/plain.png" without srcDark
    Then the figure has no dark variant

  Scenario: A missing dark file is a clear build error
    Given an image "images/chart.png" of 800 by 600 pixels
    When I render the image "images/chart.png" with srcDark "images/gone.png"
    Then the build fails naming "images/chart.png" and "images/gone.png"

  Scenario: A dark file with another aspect ratio is a build error
    Given an image pair "images/chart.png" of 800 by 600 pixels, and a dark file "images/wide.png" of 800 by 400 pixels
    When I render the image "images/chart.png" with srcDark "images/wide.png"
    Then the build fails naming "images/chart.png" and "aspect ratio"
