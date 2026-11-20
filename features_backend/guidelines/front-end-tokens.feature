Feature: The standard front end's sizes are design tokens written at the sizes people see
  Papyrus ships one set of design tokens for text, space, shape and layout, written in the sizes readers actually get: one value for
  compact screens (under 600 pixels) and one for wide screens, with no multiplier and no second stylesheet. Text has a floor in
  rendered pixels (reading text 18, interface text 14, labels 13), and the floors are tokens too. A checker refuses any text token below
  its floor in either layout, any line height that is off the rhythm or leaves the text too little room, and any stylesheet that sets a
  text size with a literal length instead of a token, so the floors cannot be bypassed. The stylesheet the pages link is generated from
  the one token source and a test fails when it is stale.

  Scenario: The shipped tokens meet the size policy in both layouts
    Given the shipped design tokens
    When the tokens are checked against the size policy
    Then no problem is reported

  Scenario: A text size below its floor is refused naming the token and the layout
    Given the shipped design tokens with the body text set to 16 pixels on wide screens
    When the tokens are checked against the size policy
    Then the check names text.body.wide as 16px below the reading floor of 18px

  Scenario: A line height off the rhythm is refused
    Given the shipped design tokens with the caption line height set to 18 pixels on wide screens
    When the tokens are checked against the size policy
    Then the check says the caption line height is not a whole number of rhythm steps

  Scenario: A stylesheet that sets text with a literal length is refused
    Given a stylesheet that sets a heading to 12px
    When the stylesheet is checked against the size policy
    Then the check says the size is not a token

  Scenario: The wide layout overrides only what differs
    Given the shipped design tokens
    When the token stylesheet is generated
    Then compact values are the defaults, and the wide block lists only tokens whose value changes
