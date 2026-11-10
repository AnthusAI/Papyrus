Feature: The Story editor's Section picker lists the site's sections and shows the Story's own
  The newsroom shell loads a summary of the site, which carries no sections. The Story editor therefore reads the site's sections itself, once, with the
  editor's session, and offers every enabled section in the site's order. The picker always shows the section the Story has, even before the list has
  loaded or when the section is disabled, so a Story set to Security never reads as having no section. Choosing a section marks the draft changed and
  saves it with the version in the same field the command line and the public site read.

  Scenario: The picker offers the site's enabled sections
    Given a site with the sections Methods and Security enabled and Retired disabled
    When the editor opens the Section picker on a Story with no section
    Then the picker offers Methods then Security and not Retired

  Scenario: The picker shows the Story's own section
    Given a site with the sections Methods and Security enabled and Retired disabled
    When the editor opens a Story whose section is Security
    Then the picker shows Security and not No section

  Scenario: The picker shows the Story's section before the list loads
    Given a Story whose section is Security and a site whose sections have not loaded
    Then the picker still shows Security, and a disabled section the Story still has stays visible
