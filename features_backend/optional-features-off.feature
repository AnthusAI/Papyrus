Feature: Optional backend features are off unless a site turns them on
  A site's backend has four optional features: the console responder, inbound email, Slack and storage backups. None of them is on by default, for any
  site, so a new site never builds something it did not ask for. A feature that is turned on must carry what it needs, and the build and the infrastructure
  synth both fail, naming the flag and what is missing, when it does not. Nothing is defaulted, skipped or worked around: the console responder runs a
  container image that Papyrus does not build, so it needs a prebuilt image named by the site; inbound email needs the site's own domain and hosted zone.

  Scenario: A site that sets nothing gets none of the four features
    When the backend resolves its features with nothing set
    Then the console responder, inbound email, Slack and storage backups are all off

  Scenario: A site turns a feature on with its branch variable
    When the backend resolves its features with "PAPYRUS_ENABLE_STORAGE_BACKUPS" set to "true"
    Then storage backups are on and the other three are off

  Scenario: The console responder without its image fails the build, naming the flag and the missing variable
    When the backend resolves its features with "PAPYRUS_ENABLE_CONSOLE_RESPONDER" set to "true"
    Then the build fails saying "PAPYRUS_ENABLE_CONSOLE_RESPONDER is on but PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI is not set"

  Scenario: Inbound email without its domain and zone fails, naming everything that is missing
    When the backend resolves its features with "PAPYRUS_ENABLE_INBOUND_EMAIL" set to "true"
    Then the build fails saying "PAPYRUS_INBOUND_EMAIL_DOMAIN, PAPYRUS_ROUTE53_HOSTED_ZONE_ID, PAPYRUS_ROUTE53_HOSTED_ZONE_NAME are not set"

  Scenario: The synth of a site fails the same way before anything is built
    When the infrastructure reads a site whose environment sets "PAPYRUS_ENABLE_CONSOLE_RESPONDER" to "true"
    Then the synth fails saying "PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI"

  Scenario: A flag that is not true or false is refused at synth
    When the infrastructure reads a site whose environment sets "PAPYRUS_ENABLE_SLACK" to "yes"
    Then the synth fails saying "must be the string"

  Scenario: Every example site says nothing and builds none of the four features
    When the infrastructure reads each example site as it is
    Then every example site is accepted
