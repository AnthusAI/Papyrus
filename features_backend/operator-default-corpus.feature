Feature: Reference commands without a corpus key use the publication the signed-in site serves
  A person signed in to a newsroom runs `papyrus references list` or `references show` without naming a corpus. The command must look in
  the corpus that site serves, never in a default that shipped inside the command-line tool for some other publication. A corpus the site
  or the operator chose still wins, and a corpus key given on the command line is used as given. When the site names no single corpus, the
  command fails and says to pass a corpus key; it never guesses. An operator on the IAM lane keeps the default that shipped with the tool.

  Background:
    Given an empty directory with no steering file and no operator configuration of its own

  Scenario: A signed-in list uses the site's canonical corpus
    Given the signed-in site serves the one canonical corpus "ai-ml-research"
    When a signed-in person lists references with no corpus key
    Then the references are listed from the corpus "ai-ml-research"
    And the printed header names the corpus "ai-ml-research"

  Scenario: A corpus key on the command line is used as given
    When a signed-in person lists references with the corpus key "chosen-corpus"
    Then the references are listed from the corpus "chosen-corpus"

  Scenario: A site with several canonical corpora is an error, not a guess
    Given the signed-in site serves the canonical corpora "one" and "two"
    When a signed-in person lists references with no corpus key
    Then the command fails and tells the person to pass a corpus key

  Scenario: A site with no canonical corpus is an error, not a guess
    Given the signed-in site serves no canonical corpus
    When a signed-in person lists references with no corpus key
    Then the command fails and tells the person to pass a corpus key

  Scenario: An operator on the IAM lane keeps the default shipped with the tool
    Given the signed-in site serves the one canonical corpus "ai-ml-research"
    When an operator on the IAM lane lists references with no corpus key
    Then the references are listed from the corpus the tool ships as its default

  Scenario: A steering file the site chose wins over the site's canonical corpus
    Given the signed-in site serves the one canonical corpus "ai-ml-research"
    And the site chose a steering file whose canonical corpus is "site-chosen-corpus"
    When a signed-in person lists references with no corpus key
    Then the references are listed from the corpus "site-chosen-corpus"

  Scenario: The show command looks in the site's canonical corpus
    Given the signed-in site serves the one canonical corpus "ai-ml-research"
    When a signed-in person shows a reference with no corpus key
    Then the reference is looked up in the corpus "ai-ml-research"
