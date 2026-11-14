Feature: A run writes where it is told to, or stops
  A research or reporting run keeps its files in a run directory. The directory is the repository's .papyrus-runs, or the directory the
  environment names in PAPYRUS_RUNS_DIR (a Lambda names one under /tmp, because its code directory is read-only). The code used to try
  the repository first and quietly move to the system temporary directory when that failed, so a misconfigured machine kept running
  and left its files somewhere nobody looked. A directory that cannot be written is now an error that names the setting.

  Scenario: A configured run directory is used
    Given PAPYRUS_RUNS_DIR names a writable directory
    When a run directory is requested
    Then the run directory is created under the configured directory

  Scenario: An unwritable run directory is an error that names the setting
    Given PAPYRUS_RUNS_DIR names a directory that cannot be written
    When a run directory is requested
    Then the request fails and the error names PAPYRUS_RUNS_DIR
