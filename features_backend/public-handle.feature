Feature: A public handle is the only name the public Messages show
  A person may choose a public handle in their settings. The public threads file shows that handle next to their messages and
  nothing else about them. Without a handle a message is shown as Editor, or as AI when it is not a person's. Only the person can
  set or clear their own handle, and a handle belongs to one person on a site.

  Scenario: A person sets a public handle and it is shown on their public messages
    Given a person who set the public handle "Ryan-P"
    When their message is prepared for the public threads file
    Then the author is shown as the handle "ryan-p"

  Scenario: A person without a handle is shown as Editor
    Given a person who has no public handle
    When their message is prepared for the public threads file
    Then the author is shown as the label "Editor"
    And a message written by AI is shown as the label "AI"

  Scenario Outline: A handle must be 3 to 24 lowercase letters, digits or hyphens and may not contain an at sign
    When a person tries the handle "<input>"
    Then the handle is <outcome>

    Examples:
      | input                     | outcome                    |
      | ryan                      | accepted as "ryan"         |
      | Ryan-Parker               | accepted as "ryan-parker"  |
      | ab                        | refused as "length"        |
      | abcdefghijklmnopqrstuvwxy | refused as "length"        |
      | -ryan                     | refused as "characters"    |
      | ry_an                     | refused as "characters"    |
      | ryan@example              | refused as "at-sign"       |
      | admin                     | refused as "reserved"      |

  Scenario: The Python and TypeScript rules agree on every shared vector
    When every shared handle vector is checked
    Then the Python rules give the answer written in the vector

  Scenario: A handle that another person already uses is refused
    When the console's resolver tests run for "another profile already uses"
    Then they pass

  Scenario: Only the person can set their own handle
    When the console's resolver tests run for "caller's own profile"
    Then they pass

  Scenario: Clearing the handle returns the person to the anonymous label
    Given a person who set the public handle "ryan-p"
    When they clear the handle
    Then their message is shown as the label "Editor"
    And the console's resolver tests for "clearing the handle" pass

  Scenario: No email, sub or UUID appears in the public threads file whether or not handles are set
    Given a person whose profile has an email, a sub and a UUID
    When their message is prepared once with a handle and once without
    Then neither public author contains an email, a sub or a UUID
    And a stored handle that looks like an email is shown as Editor
