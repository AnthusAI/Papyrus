Feature: A site's brand pack and notice are applied by the standard front end
  A site on the standard front end changes how it looks with a brand pack: one JSON file of colours for light and dark, two fonts the
  platform hosts, a corner scale and an ornament level. The projection checks the pack against the platform policy, links the shared
  publication theme, and writes one small stylesheet of custom properties named by its hash; the shared stylesheets are the same for every
  site. A site that is satire (or drafted by AI) says so once, in its settings, and the standard front end says it on every page, in
  the Markdown twin, in llms.txt, in the feeds and in the structured data.

  Scenario: A valid pack gives a branded site with one small brand stylesheet
    Given a site with a valid brand pack
    When the branded site is projected
    Then every page links the shared theme and then the brand stylesheet last, and that stylesheet carries the pack in light and dark

  Scenario: A pack that fails the policy stops the build and names the problem
    Given a site whose brand pack has body text too faint in dark mode
    When the branded site is projected
    Then the build stops naming ink on bg in the dark theme

  Scenario: A font the platform does not host yet is refused saying so
    Given a site whose brand pack asks for the heading font Lora
    When the branded site is projected
    Then the build stops saying the platform does not host the font yet

  Scenario: The notice is said everywhere
    Given a site with the notice "Satire. Everything on this site is invented."
    When the branded site is projected
    Then it is on every kind of page, in the Markdown twin, in llms.txt, in both feeds and in the structured data

  Scenario: The notice is one small quiet line, not a box
    Given a site with the notice "Satire. Everything on this site is invented."
    When the branded site is projected
    Then the notice is one plain line under the masthead, and a site with no notice shows nothing

  Scenario: A site may fix the notice to the bottom of the viewport
    Given a site with the notice placement "fixed-footer"
    When the branded site is projected
    Then every page has one slim notice bar after the main content and the footer, and the stylesheet fixes it to the bottom, pads the page so it never covers content and clears the phone safe area
    And the Markdown twin and the structured data carry the notice as before

  Scenario: Placement is inline or fixed-footer
    Given a site with the notice placement "banner"
    When the branded site is projected
    Then the build stops naming the notice placement

  Scenario: A site without a pack or notice is unchanged
    Given a site with no brand pack and no notice
    When the branded site is projected
    Then no page links the shared theme or a brand stylesheet and none carries a notice
