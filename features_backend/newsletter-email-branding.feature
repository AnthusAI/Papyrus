Feature: Newsletter emails carry the site's branding
  A site's newsletter theme can describe its brand: a header band with a wordmark, a footer band, branded buttons and a
  mono label font. The confirmation, alert and roundup emails all use it. A site that sets none of it keeps the plain
  layout it always had. Email clients drop web fonts, so the wordmark is an image with alt text, and the plain-text part
  says the same thing in words. Nothing relies on colour alone: links stay underlined and buttons keep a label and a border.

  Scenario: The header band holds the wordmark and the list name
    Given a branded theme with a lime header band and a wordmark image 168 by 40 with alt text "Shipped"
    When an alert email is rendered for the list "Alerts: Open weights"
    Then the header band is lime and holds an image with alt text "Shipped", width 168 and height 40
    And the list name "Alerts: Open weights" is in the header band
    And the plain-text part starts with "Shipped"

  Scenario: Without an image the header band shows the site name
    Given a branded theme with a lime header band and no wordmark image
    When an alert email is rendered for the list "Alerts: Open weights"
    Then the header band shows the site name as text
    And the email has no wordmark image

  Scenario: The footer band carries the links, the reason and the postal address
    Given a branded theme with a lime footer band and a wordmark image 168 by 40 with alt text "Shipped"
    When a roundup email is rendered for the list "The Shipped roundup"
    Then the footer band is lime and shows the wordmark, an underlined unsubscribe link and an underlined preferences link
    And the footer band shows the reason sentence and the postal address

  Scenario: The confirmation button has a fill, a label and a border
    Given a branded theme with lime buttons, ink button text and an ink button border
    When the confirmation email is rendered
    Then the button is filled lime, has the label "Confirm subscription" and a 1.5px ink border
    And the button has square corners

  Scenario: Links in the body stay underlined
    Given a branded theme with a lime header band and a wordmark image 168 by 40 with alt text "Shipped"
    When a roundup email is rendered for the list "The Shipped roundup"
    Then every link in the body is underlined

  Scenario: A theme without branding renders exactly as before
    Given a theme with only an accent, text and background
    When the confirmation email and an alert email are rendered
    Then they have no header band, footer band or branded button
    And their markup matches what the renderer produced before branding existed

  Scenario: Dark mode swaps the page and keeps the brand
    Given a branded theme with a lime header band and a lime footer band
    When an alert email is rendered for the list "Alerts: Open weights"
    Then the email declares both colour schemes
    And in dark mode the page and the panels turn to dark ink and the text to paper
    And in dark mode the bands stay lime with ink text

  Scenario Outline: A branding value that could break out of the markup is refused
    When a theme is built with <field> set to "<value>"
    Then building the theme fails

    Examples:
      | field            | value                            |
      | headerBand       | red;                             |
      | buttonFill       | url(x)                           |
      | footerBand       | #fff"><script>                   |
      | wordmarkImageUrl | http://example.com/wordmark.png  |
