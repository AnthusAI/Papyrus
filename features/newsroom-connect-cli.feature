@brand-agnostic @connect-cli-fixtures
Feature: The console shows an editor how to connect the Papyrus CLI or a reporting agent to this site
  A reporting agent cannot work until it has signed in to the site as a person. From the signed-in console, under Settings, the page
  "Connect the CLI or an agent" gives the commands to do that, with a copy button on each, filled in from the site's own address so
  nobody types a host name. The values come from the same code that serves the site's public sign-in file, so the page cannot
  disagree with it. There are two ways in: on a computer with a browser, and, only on a site whose sign-in file names a remote
  sign-in broker, for an agent with no browser, where the person approves on their phone. The words are for an editor who does not
  use a terminal: connecting lets the agent act as that person, with that person's permissions and no more. A Story's reporting view
  carries one small link to the page, and so does the account menu. These scenarios use synthetic sites in an isolated browser at
  375 and 1440 pixels, in light and dark, and never touch production or sign in anywhere. Seeing and ending active CLI sign-ins is not
  part of this page, because the backend does not list them.

  Scenario: The commands are filled in from the site's own address
    Given a synthetic site whose sign-in file is published
    When the page is built for it
    Then the sign-in command names the site's host, and the check and sign-out commands name it too
    And a site with its console on its own host gets that host, because the sign-in file names it
    And a site that does not publish the sign-in file gets no commands and a plain explanation

  Scenario: Signing in from a phone is offered only where the site switched it on
    Given a synthetic site that names a remote sign-in broker and one that does not
    When the editor opens the page at 375 and 1440 pixels
    Then the first site shows the remote command straight after install, for an agent on a cloud computer approved from a phone, and says to open the link yourself
    And the second shows no remote command and says approving from a phone is not switched on
    And a site with no sign-in file shows no command at all

  Scenario: Every command has a copy button that says it copied
    Given a synthetic site that names a remote sign-in broker
    When the editor presses the copy button of the remote command
    Then exactly that command is copied
    And the button changes its icon and says Copied, so the change is not colour alone

  Scenario: Flat tones, rounded rectangles, no borders, no drop-downs
    Given a synthetic site that names a remote sign-in broker
    When the editor opens the page at 375 and 1440 pixels, in light and dark
    Then no element has a visible border, outline or shadow and nothing scrolls sideways
    And the panels are rounded rectangles that differ from the page only by tone
    And there are no drop-downs and every icon is a Lucide icon

  Scenario: The words are plain and accurate
    Given a synthetic site that names a remote sign-in broker
    When the editor reads the page
    Then it says the agent acts as the editor and can do what the editor can do and nothing more
    And it says how to end the sign-in on that computer
    And it never says Organization or desk
