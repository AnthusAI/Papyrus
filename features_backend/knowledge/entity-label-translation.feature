@backend @multilingual
Feature: A section or a concept is named in each language by a checked translation
  A name in another language is made by one procedure for sections and concepts alike. The glossary decides a name it covers, the house model translates the
  rest and may answer that the language has no settled term, code and the bilingual judge check the words, and a clean label is current, which is what
  the language's pages show (labelled AI-translated). A name two things share, or one with no equivalent term, is held for a person and never published.
  A person's wording is never overwritten, and a label made from the current words is not made again. (docs/multilingual-labels.md; an in-memory site and a
  scripted model: nothing reaches the network.)

  Scenario: A clean label is current and records the words it came from
    Given a site with the section "Agents" described as "Machines that plan and act on their own."
    And the model names it "Agentes"
    When the section is named in "es-419"
    Then the label "Agentes" is current, made by the machine, with exact equivalence
    And naming it again asks the model nothing

  Scenario: A name that another section already has is held
    Given a site with the section "Agents" described as "Machines that plan and act on their own."
    And another section already has the "es-419" name "Agentes"
    And the model names it "Agentes"
    When the section is named in "es-419"
    Then the label is held because "Agentes" is already the name of the other section
    And the label is in the work list of "es-419" as held

  Scenario: A term with no settled equivalent is held with the model's reason
    Given a site with the section "Agents" described as "Machines that plan and act on their own."
    And the model finds no equivalent term, saying "no settled term"
    When the section is named in "es-419"
    Then the label is held because there is no equivalent term in "es-419"

  Scenario: The glossary decides the name
    Given a site with the section "Agents" described as "Machines that plan and act on their own."
    And the glossary renders "Agents" as "Agentes IA"
    And the model names it "Otra cosa"
    When the section is named in "es-419"
    Then the label "Agentes IA" is current, made from the glossary

  Scenario: A person's wording is never overwritten
    Given a site with the section "Agents" described as "Machines that plan and act on their own."
    And the model names it "Agentes"
    And the section was named in "es-419" and a person pinned the wording
    When the section's description changes and it is named again in "es-419"
    Then the label stays as the person wrote it and the model was not asked
