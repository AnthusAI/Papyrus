Feature: A guideline is a folder with a GUIDELINE.md that can be checked offline
  One guideline is one folder holding GUIDELINE.md: flat front matter (id, type papyrus:Guideline, name, description, kind, scope, severity, and optionally
  language, avoid, prefer, pattern and maxLength) and a prose body. The kind is one of writing, image and announcement; the scope is publication,
  section/<id> or channel/<name> (channel/x, channel/linkedin and channel/email are how a delivery's tailoring rules are written); the severity is error,
  warn or guidance. A set of guideline folders is valid or refused whole: a missing key, an unknown key, a nested value or a bad severity is named by
  guideline and key, and nothing is checked against a refused set. papyrus guidelines check reads the folders and the files to check, decides every rule a
  program can decide (a listed word, a pattern, a length) with no network and no model, and lists each rule that needs judgement as not checked offline. It
  never guesses and it never connects to a site. Its exit status is 1 only when a guideline with severity error finds something; warnings are reported and
  guidance is never checked. The writing guidelines are stored in the cloud as these same files (guidelines-cloud-files.feature).

  Scenario: A guideline folder with every key is valid
    Given a guidelines folder with the guideline "plain-claims" of kind writing, scope publication and severity error that avoids "we believe"
    When the guideline folders are loaded
    Then the set is accepted with 1 guideline
    And the guideline "plain-claims" keeps its prose body

  Scenario: Channel scopes are allowed
    Given a guidelines folder with the guideline "x-voice" of kind announcement, scope channel/x and severity warn that avoids "game-changer"
    And the guideline "linkedin-voice" of kind announcement, scope channel/linkedin and severity warn with only prose
    And the guideline "email-voice" of kind announcement, scope channel/email and severity guidance with only prose
    When the guideline folders are loaded
    Then the set is accepted with 3 guidelines

  Scenario: The file form uses the kinds the guideline system already has
    Then every kind of the file form is a registered guideline kind

  Scenario Outline: A guideline folder is refused for a bad front matter
    Given a guidelines folder with a guideline "plain-claims" whose front matter has <problem>
    When the guideline folders are loaded
    Then the set is refused
    And the refusal names the guideline "plain-claims", the key "<key>" and the code "<code>"

    Examples:
      | problem                              | key        | code          |
      | no kind                              | kind       | missing_key   |
      | no id                                | id         | missing_key   |
      | an unknown key "tone"                | tone       | unknown_key   |
      | a nested value for avoid             | avoid      | nested_value  |
      | a nested object for scope            | scope      | nested_value  |
      | the severity "fatal"                 | severity   | invalid_value |
      | the kind "video"                     | kind       | invalid_value |
      | the scope "channel"                  | scope      | invalid_value |
      | an id that is not a permanent id     | id         | invalid_value |
      | a name that is not the folder's name | name       | invalid_value |
      | a maxLength of zero                  | maxLength  | invalid_value |
      | a pattern that is not a pattern      | pattern    | invalid_value |
      | a list for severity                  | severity   | invalid_value |

  Scenario: A folder without GUIDELINE.md, a file without front matter and a repeated id are refused
    Given a guidelines folder with an empty folder "no-file"
    And a guideline file "no-front-matter" with no front matter
    And the guidelines "twin-a" and "twin-b" that share one id
    When the guideline folders are loaded
    Then the set is refused
    And the refusal names the guideline "no-file" with the code "missing_file"
    And the refusal names the guideline "no-front-matter" with the code "missing_front_matter"
    And the refusal names the guideline "twin-b" with the code "duplicate_id"

  Scenario: A listed word is found with no network
    Given a guidelines folder with the guideline "plain-claims" of kind writing, scope publication and severity error that avoids "we believe"
    And a file to check that says "We believe the claim is red."
    When the file is checked offline with the network closed
    Then the check finds the phrase "We believe" against "plain-claims" on line 1
    And the command exits with status 1

  Scenario: A rule that needs judgement is listed as not checked and never guessed
    Given a guidelines folder with the guideline "plain-claims" of kind writing, scope publication and severity error that avoids "we believe"
    And the guideline "earned-tone" of kind writing, scope publication and severity error with only prose
    And a file to check that says "The claim is red."
    When the file is checked offline with the network closed
    Then the check finds nothing
    And the guideline "earned-tone" is listed as not checked offline because it needs judgement
    And the command exits with status 0

  Scenario: Exit status reflects error findings only
    Given a guidelines folder with the guideline "soft-words" of kind writing, scope publication and severity warn that avoids "arguably"
    And the guideline "just-advice" of kind writing, scope publication and severity guidance that avoids "arguably"
    And a file to check that says "This is arguably fine."
    When the file is checked offline with the network closed
    Then the check reports 1 warning and 0 errors
    And the guideline "just-advice" produced no finding
    And the command exits with status 0

  Scenario: Patterns and lengths are decided offline
    Given a guidelines folder with the guideline "no-shouting" of kind writing, scope publication and severity error that matches the pattern "!{2,}"
    And the guideline "short-post" of kind announcement, scope publication and severity error with a maxLength of 20
    And a file to check that says "Big news!! Read it now, it is long."
    When the file is checked offline with the network closed
    Then the check finds the rule "pattern" against "no-shouting"
    And the check finds the rule "maxLength" against "short-post"

  Scenario: A channel guideline applies only when its scope is asked for
    Given a guidelines folder with the guideline "x-voice" of kind announcement, scope channel/x and severity error that avoids "game-changer"
    And a file to check that says "A game-changer for readers."
    When the file is checked offline with the network closed
    Then the check finds nothing
    When the file is checked offline for the scope "channel/x"
    Then the check finds the phrase "game-changer" against "x-voice" on line 1

  Scenario: A guideline for another language is not decided unless the language is given
    Given a guidelines folder with the guideline "es-words" of kind writing, scope publication and severity error that avoids "creemos" in the language es
    And a file to check that says "Creemos que es rojo."
    When the file is checked offline with the network closed
    Then the check finds nothing
    And the guideline "es-words" is listed as not checked offline because it is written for es
    When the file is checked offline in the language "es"
    Then the check finds the phrase "Creemos" against "es-words" on line 1

  Scenario: A refused set checks nothing
    Given a guidelines folder with a guideline "plain-claims" whose front matter has the severity "fatal"
    And a file to check that says "Anything."
    When the file is checked offline with the network closed
    Then the command refuses the guidelines, names "severity" and exits with status 2
    And nothing was checked

  Scenario: papyrus guidelines check --help sends nothing
    When an agent runs "papyrus guidelines check --help" with no site and no sign-in
    Then the printed usage shows "--dir" and says it is read only
    And no connection to a site was opened
