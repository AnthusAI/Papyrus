Feature: A signed-in editor or agent saves a version as themselves, reads an assignment's direction, and gets a plain message from the root guard
  Three gaps found testing the CLI against a live site. A person signed in with `papyrus login` should not have to type a name to save a
  Story version: the version records the person who signed in, the way linking a Reference already does, and a name they type is ignored
  because the backend does not verify one. An operator on AWS credentials has no sign-in to name anyone, so that lane still has to say who
  it is. An agent that is handed an Assignment needs to read what it was asked to do, so `assignments show` prints the Assignment's
  direction, whole, with a multi-line direction readable in the tab-separated output. The guard that stops an install from running
  inside a different Papyrus checkout is unchanged; only its message now tells the person to run from another folder and says that
  the override is an explicit choice. Nothing here touches a real site, login, network or AWS.

  Scenario: A signed-in person saves a version without naming an author
    Given a Story with one version
    And the CLI is signed in as "Ada Example"
    When the person saves a new version without an author label
    Then the new version is recorded as written by "Ada Example"

  Scenario: A name typed while signed in cannot name someone else
    Given a Story with one version
    And the CLI is signed in as "Ada Example"
    When the person saves a new version with the author label "Someone Else"
    Then the new version is recorded as written by "Ada Example"
    And a warning says the author label is ignored

  Scenario: A signed-in session that names no one saves nothing
    Given a Story with one version
    And the CLI is signed in but its session names no one
    When the person saves a new version without an author label
    Then nothing is saved and the person is told to check whoami

  Scenario: An operator on AWS credentials must still say who is saving
    Given a Story with one version
    And the CLI uses the IAM lane for a save
    When the person saves a new version without an author label
    Then the save is refused because the author label is required
    When the person saves a new version with the author label "ChatGPT"
    Then the new version is recorded as written by "ChatGPT"

  Scenario: An assignment's direction is printed whole
    Given an Assignment whose direction is "Look into the facial recognition story."
    When a person shows the Assignment
    Then one direction row holds "Look into the facial recognition story."

  Scenario: A multi-line direction stays readable in the tab-separated output
    Given an Assignment whose direction has three lines with a blank line between the first two
    When a person shows the Assignment
    Then the direction prints as one row per line, in order, the blank line as an empty value
    And every row still has the same tab-separated columns

  Scenario: A direction kept in the Assignment's metadata attachment is read from there
    Given an Assignment whose direction is only in its metadata attachment
    When a person shows the Assignment
    Then one direction row holds "Compare the two vendors' claims."

  Scenario: An Assignment with no direction prints no direction row
    Given an Assignment with no direction
    When a person shows the Assignment
    Then no direction row is printed

  Scenario: The root guard tells the person to run from another folder and names the override as a choice
    Given an install whose root differs from the Papyrus checkout the person is inside
    When the person runs a command
    Then the command is still blocked
    And the message tells the person to run it from another folder
    And the message says the cross-root flag is an explicit choice

  Scenario: The root guard still lets a matching root through
    Given an install whose root is the Papyrus checkout the person is inside
    When the person runs a command
    Then the command is not blocked
