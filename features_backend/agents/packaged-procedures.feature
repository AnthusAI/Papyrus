Feature: The Tactus procedures ship in the wheel and are found by their kind
  The research, reporting, summarisation, ontology and email procedures are Tactus files in the
  repository's procedures/newsroom/ folder. They are also the files a PyPI install, a container job
  and a local pod run, and none of those has a Papyrus checkout. So the wheel carries every
  procedure under papyrus_content/data/procedures/, the registry in papyrus-required-procedures.json
  names the file for each procedure kind, and the code asks for a kind and gets the file through
  importlib.resources. In a checkout the repository's own file is the one that runs, so an edit to a
  procedure is seen at once and an operator can override one by pointing PAPYRUS_ROOT at a folder.

  Scenario: The built wheel contains the file of every registered kind
    Given the wheel built from this checkout
    Then every kind in the procedure registry has its file in the wheel
    And each packaged procedure in the wheel is the same text as the file in the checkout

  Scenario: A kind is found from an unpacked wheel away from the checkout
    Given the wheel built from this checkout
    When the wheel is unpacked away from the checkout and every registered kind is looked up
    Then every kind resolves to a file inside the unpacked wheel that declares that kind
    And the procedure registry check passes there
    And there is no procedures folder in the unpacked wheel's root

  Scenario: The ontology commands find their procedures in an unpacked wheel
    Given the wheel built from this checkout
    When the wheel is unpacked away from the checkout and the ontology preflight names its procedures
    Then both ontology procedures are found in the unpacked wheel

  Scenario: A checkout's own procedure file runs instead of the packaged one
    Given a root with its own procedures/newsroom/reporter.tac
    Then the reporting procedure resolves to the root's file
    When that root file is removed
    Then the reporting procedure resolves to the packaged file

  Scenario: The repository path and the packaged path are one file
    Then every procedure in procedures/newsroom/ is a link to the packaged file
    And no packaged procedure lacks a repository path
