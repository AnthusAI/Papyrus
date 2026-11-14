Feature: A brand pack is checked against the platform policy before a shared-tier site uses it
  An owner on the shared tier changes how a site looks only through its brand pack: a name, a logo, a wordmark, one colour for each
  role in light and in dark, two fonts from an allow-list and an image-style slot for still pictograms. The pack is a versioned JSON
  schema, and a validator applies the platform policy: every text and fill pair meets the WCAG contrast minimum in both themes, the
  pairs that must be told apart differ in lightness and not only in hue (many readers cannot tell certain hues apart), and fonts come from the allow-list. A refusal names the failing pair or setting, the theme and the measured ratio, so
  the owner knows what to change. Custom CSS, sizes, spacing and borders are not part of the pack and are refused.

  Scenario: A valid pack passes in both themes
    Given a brand pack for Lantern Quay with its own colours and fonts from the allow-list
    When the brand pack is validated
    Then the brand pack is accepted in light and in dark

  Scenario: A low-contrast pack is refused naming the pair
    Given a brand pack whose body text is too faint in dark mode
    When the brand pack is validated
    Then it is refused naming ink on bg in the dark theme with its measured contrast ratio

  Scenario: A pair that differs only in hue is refused as not told apart by lightness
    Given a brand pack whose dark-mode rule colour has the same lightness as the page
    When the brand pack is validated
    Then it is refused naming rule on bg in the dark theme as needing a lightness difference

  Scenario: A font outside the allow-list is refused
    Given a brand pack that asks for the heading font Comic Sans MS
    When the brand pack is validated
    Then it is refused naming the heading font and listing the allowed fonts

  Scenario: Custom CSS is refused
    Given a brand pack that carries custom CSS
    When the brand pack is validated
    Then it is refused naming the css setting as not allowed on the shared tier

  Scenario: An unknown setting is refused
    Given a brand pack with a setting the format does not have
    When the brand pack is validated
    Then it is refused naming the unknown setting

  Scenario: The shared vectors give the same answers as the validator
    Given the shared brand pack vectors
    When every vector is validated
    Then each vector gets its expected result
