@brand-agnostic
Feature: Blog layout engine
  The blog presentation sizes featured images and copy on a vertical rhythm
  grid. Every height and gap it produces is a whole number of rhythm rows.

  Scenario: Heights snap to the default rhythm rows
    Given the default blog vertical rhythm
    Then the rhythm row height should be 16 pixels
    And a height of 30 pixels should reserve 32 pixels
    And a height of 30 pixels should snap to the nearest row at 32 pixels

  Scenario: Blog copy uses a two-row line box
    Given the default blog vertical rhythm
    When I derive the blog text style for the font "Serif"
    Then the blog font size should be 18 pixels
    And the blog line height should be 32 pixels
    And the blog line paint height should equal the line height

  Scenario Outline: A featured image float is sized on the rhythm
    Given the default blog vertical rhythm
    When I solve a featured float for a <container> pixel container in a <viewport> pixel viewport at item <index>
    Then the featured image width should be <image width> pixels
    And the featured gap should be <gap> pixels
    And the featured image height, media height and gap should be whole rhythm rows

    Examples:
      | container | viewport | index | image width | gap |
      | 800       | 1280     | 0     | 384         | 32  |
      | 600       | 900      | 0     | 288         | 32  |
      | 360       | 390      | 0     | 160         | 16  |
      | 800       | 1280     | 1     | 384         | 64  |

  Scenario: Featured items with an image always float
    Then the featured layout mode at 540 pixels with an image should be "float"
    And the featured layout mode at 540 pixels without an image should be "stacked"
