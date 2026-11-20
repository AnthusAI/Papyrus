Feature: A translation worker keeps the tenant of its own publication
  A translation worker takes its tenant from the publication the router launched it for. It never takes it from the workflow's
  input or from an earlier invocation in the same process. An original that belongs to another publication is not eligible,
  whatever the input claims.

  Scenario: A tenant-prefixed original remains eligible in a launched worker
    Given a localization worker launched for a tenant publication
    When the worker checks that publication's original story
    Then the original is eligible for localization

  Scenario Outline: Source eligibility fails closed outside the original publication
    Given a localization worker with tenant "<tenant>"
    When it checks lineage "<lineage>" in language group "<group>"
    Then source eligibility is "<eligible>"
    Examples:
      | tenant              | lineage  | group                        | eligible |
      | missing             | story-1  | machines-on-machines#story-1 | no       |
      | other               | story-1  | machines-on-machines#story-1 | no       |
      | machines-on-machines | story-es | machines-on-machines#story-1 | no       |
      | missing             | story-1  | story-1                      | yes      |
