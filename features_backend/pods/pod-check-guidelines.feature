@pod
Feature: papyrus pod check validates a pod's guideline folders with the guideline checker's own validation
  A pod may hold a guidelines folder: one folder per guideline, each with a GUIDELINE.md (guidelines-files.feature). `papyrus pod check` has no
  second validator. It calls the same load_directory and validate_meta that papyrus guidelines check calls, and reports each problem on its own
  line with the file and the key named. A guidelines folder is not notes: its files are never read as typed notes, and a pod with no guidelines
  folder is checked exactly as before. The check only reads, and it never contacts a site.

  Scenario: A pod with a valid guideline folder passes
    Given a started pod
    And the pod has the guideline "plain-claims" of kind writing, scope publication and severity error that avoids "we believe"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"
    And the pod report says "level: 1 (0 of 0 notes typed)"

  Scenario: A guideline folder is not read as a typed note
    Given a started pod
    And the pod has the guideline "plain-claims" of kind writing, scope publication and severity error that avoids "we believe"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report does not say "papyrus:Guideline"

  Scenario: A pod with no guideline folder is unaffected
    Given a started pod
    And the pod has no guidelines folder
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"
    And the pod report does not say "guidelines"

  Scenario: A pod with a guideline folder that holds no guidelines is refused
    Given a started pod
    And the pod has an empty guidelines folder
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "holds no guideline folders" for the note "guidelines"

  Scenario Outline: A pod with a bad guideline file is refused and the file and key are named
    Given a started pod
    And the pod has the guideline "plain-claims" whose front matter has <problem>
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "<message>" for the note "guidelines/plain-claims/GUIDELINE.md"

    Examples:
      | problem                              | message                                                    |
      | no kind                              | key 'kind' is required                                     |
      | no id                                | key 'id' is required                                       |
      | an unknown key "tone"                | key 'tone' is not a key of a guideline                     |
      | a nested value for avoid             | key 'avoid' must be flat                                   |
      | a nested object for scope            | key 'scope' must be flat                                   |
      | the severity "fatal"                 | key 'severity' must be one of error, warn, guidance        |
      | the kind "video"                     | key 'kind' must be one of writing, image, announcement     |
      | the scope "channel"                  | key 'scope' must be publication, section/<id> or channel/<name> |
      | an id that is not a permanent id     | key 'id' must be a permanent identifier                    |
      | a name that is not the folder's name | key 'name' must be the folder's name                       |
      | a maxLength of zero                  | key 'maxLength' must be a whole number above zero          |
      | a pattern that is not a pattern      | key 'pattern' '(unclosed' is not a valid pattern           |
      | a list for severity                  | key 'severity' must be a single value, not a list          |

  Scenario: A guideline folder with a file that has no front matter is refused with its file named
    Given a started pod
    And the pod has a guideline file "no-front-matter" with no front matter
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "must open with a front matter block" for the note "guidelines/no-front-matter/GUIDELINE.md"

  Scenario: Two guideline folders with the same id are both named
    Given a started pod
    And the pod has the guidelines "twin-a" and "twin-b" that share one id
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "is already the id of" for the note "guidelines/twin-b/GUIDELINE.md"

  Scenario: The pod check and papyrus guidelines check give the same verdict on a valid folder
    Given a started pod
    And the pod has the guideline "plain-claims" of kind writing, scope publication and severity error that avoids "we believe"
    When papyrus guidelines check reads the pod's guidelines folder
    And I run the pod command "papyrus pod check POD"
    Then papyrus guidelines check accepts the folder
    And the pod command exits with status 0

  Scenario Outline: The pod check and papyrus guidelines check refuse the same bad file with the same key and message
    Given a started pod
    And the pod has the guideline "plain-claims" whose front matter has <problem>
    When papyrus guidelines check reads the pod's guidelines folder
    And I run the pod command "papyrus pod check POD"
    Then papyrus guidelines check refuses the folder with the key "<key>" and the message "<message>"
    And the pod command exits with status 1
    And the pod report names the problem "<message>" for the note "guidelines/plain-claims/GUIDELINE.md"

    Examples:
      | problem                              | key    | message                              |
      | no kind                              | kind   | is required                          |
      | an unknown key "tone"                | tone   | is not a key of a guideline          |
      | a nested value for avoid             | avoid  | must be flat                         |
      | the severity "fatal"                 | severity | must be one of error, warn, guidance |
