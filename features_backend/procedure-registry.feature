Feature: Every procedure file declares its kind, and the registry agrees with the files
  A procedure is run by its kind, such as newsroom.reporting.context, not by its file name. The first
  line of every procedure file says which kind it is (-- papyrus-procedure-kind: <kind>). The registry
  in papyrus-required-procedures.json lists the file that runs for each kind, and the CLI commands in
  requiredCliProcedures each name a kind. At load, and in CI, the three are compared, so a renamed
  file, a copied file, a wrong kind or a command that points at nothing is caught before it ships
  instead of running the wrong procedure.

  Scenario: The shipped registry matches the shipped procedure files
    Given the procedure files and the registry of this checkout
    Then the registry and the procedure files agree
    And every procedure file declares its kind on its first line

  Scenario: Every CLI command resolves to a procedure file that declares the kind it needs
    Given the procedure files and the registry of this checkout
    Then every command in requiredCliProcedures resolves to a file that declares its kind

  Scenario: A procedure file that declares no kind is reported
    Given a registry of two kinds, each with a file that declares it
    When the first file loses its kind line
    Then the check names that file as declaring no kind

  Scenario: A kind line that is not the first line is reported
    Given a registry of two kinds, each with a file that declares it
    When the first file gets a comment above its kind line
    Then the check names that file as declaring no kind

  Scenario: Two files that declare the same kind are reported
    Given a registry of two kinds, each with a file that declares it
    When the second file declares the first file's kind
    Then the check names both files as declaring the same kind

  Scenario: A registry entry whose file declares another kind is reported
    Given a registry of two kinds, each with a file that declares it
    When the registry swaps the two files
    Then the check says each kind points at a file that declares the other

  Scenario: A registry entry whose file does not exist is reported
    Given a registry of two kinds, each with a file that declares it
    When the registry sends the first kind to a file that is not there
    Then the check says the first kind points at a file that is not a procedure file

  Scenario: A procedure file the registry does not list is reported
    Given a registry of two kinds, each with a file that declares it
    When a third procedure file is added that the registry does not list
    Then the check names the third file as not listed

  Scenario: A CLI command that names a kind the registry lacks is reported
    Given a registry of two kinds, each with a file that declares it
    When a CLI command is added for a kind the registry does not list
    Then the check names that command

  Scenario: Loading a procedure by kind refuses a file that declares another kind
    Given a registry of two kinds, each with a file that declares it
    When the first file is edited to declare another kind
    Then loading the first kind refuses it
