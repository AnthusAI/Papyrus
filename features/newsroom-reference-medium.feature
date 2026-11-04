@brand-agnostic
Feature: A Reference card says in words and an icon when its address is a video
  The newsroom sets a Reference's medium from its address, by rule and only where certain. A card for a Reference whose medium is video carries a
  small label with the word "Video" and a Lucide video icon, so the medium is never shown by colour alone. A Reference with no medium carries no
  label. The label is a flat tone with rounded corners and no border or outline, and nothing scrolls sideways. These scenarios use synthetic
  References in an isolated browser at 375 and 1440 pixels, in light and dark, and never touch production.

  Scenario: A video card says Video next to a video icon and an ordinary card says nothing
    Given a synthetic site with a video Reference and an article Reference
    When the editor looks at the References feed cards in light and dark at 375 and 1440 pixels
    Then the video card has a "Video" label with a Lucide video icon and the article card has none
    And the label has no border or outline and nothing scrolls sideways
