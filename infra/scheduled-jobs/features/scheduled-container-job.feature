Feature: Scheduled container jobs
  A heavy, unattended job (the weekly knowledge run is the first) runs as a chain
  of Fargate tasks from one container image, started by a weekly schedule through
  a Step Functions state machine. The same construct serves any other pipeline.
  The job has no NAT gateway, keeps its state in S3 and a DynamoDB ledger,
  reaches the AWS APIs with a least-privilege role, and tells the owner by e-mail
  when a run fails or a week is missed.
  Executable by scripts/test-scheduled-job-synth.ts (npm run test:scheduled-job-synth).

  Background:
    Given the Shipped example site config with a knowledgeRun block
    And the knowledge run stack is synthesized with an image tag

  Scenario: the job network has no NAT gateway
    Then the template has no NAT gateway and no Elastic IP
    And the VPC has two public subnets and no private subnets
    And the tasks run with a public IP address

  Scenario: S3 and DynamoDB are reached through free gateway endpoints
    Then the VPC has a gateway endpoint for S3 and a gateway endpoint for DynamoDB

  Scenario: the task security group is egress-only
    Then the security group allows all outbound traffic
    And it has no ingress rules and there are no separate ingress resources

  Scenario: every stage is a Fargate task with retries, backoff and a timeout
    Then each of the ten knowledge stages is an "ecs:runTask.sync" task on Fargate
    And each runs "papyrus knowledge cloud-run --stage <name>" in the container "job"
    And each retries task failures and ECS service errors twice, 60 seconds apart, doubling, with full jitter
    And each has a TimeoutSeconds of 7200 unless the config overrides that stage

  Scenario: stages run strictly in order and projection is last
    Then the stages are corpus-sync, topic-model, typed-extraction, publish-run, ai-review, publish-relations, snapshot, archive, wiki-sync, projection
    And each stage continues only into the next one, and only wiki-sync continues into projection
    And after projection the execution succeeds, or runs the optional trend-drafts step first

  Scenario: the weekly knowledge run drafts trend stories once the snapshot is fresh
    Given the stack parameter TrendDraftsEnabled is "true" with the publication's GraphQL endpoint and snapshot address
    When the ten knowledge stages have succeeded and projection has published the snapshot
    Then one more task, trend-drafts, runs after projection and runs the job script baked into the image
    And the script waits briefly for the published index.json to show the run week's Monday as its asOf
    And a snapshot that is still stale after those attempts is skipped with the reason in the log, and nothing is drafted
    And a fresh snapshot is read once by "papyrus ideas trends --store proposals --max 2" with IAM authentication against the endpoint
    And the OpenAI key is read from the SSM SecureString by the task role at run time and is only in the environment of that command
    And the run files private story_draft Proposals, raises one soft review request and publishes nothing

  Scenario: trend drafts are off by default and never fail the run
    Given the stack parameter TrendDraftsEnabled is "false", its default
    Then the execution goes from projection straight to Done and no trend-drafts task starts
    And when it is enabled and the step fails or times out, the execution still ends in Done
    And the failure is in the task log and no Fail state, alarm or rollback follows from it

  Scenario: a site that does not opt in gets no monitor-stories step
    Given the site's knowledgeRun block has no monitorStories setting
    Then the state machine has no monitor-stories task and no Run-monitor-stories choice
    And the stack has no MonitorStoriesEnabled parameter and the task has no MONITOR_STORIES_LIMIT setting
    And the template is otherwise what it was before the step existed

  Scenario: a site that opts in with monitorStories gets an optional step after trend-drafts
    Given the site's knowledgeRun block says monitorStories is {"limit": 2}
    Then the stack has a MonitorStoriesEnabled parameter that is "false" by default
    And trend-drafts continues into the Run-monitor-stories choice, also when trend-drafts is switched off
    And when MonitorStoriesEnabled is "true", one more task, monitor-stories, runs the job script baked into the image with the AppSync endpoint of trend-drafts
    And the task gets MONITOR_STORIES_LIMIT 2, and 3 when the block gives no limit
    And the script calls "papyrus ideas monitor-stories --store proposals" with IAM authentication and writes its own ledger row with its cost
    And it publishes nothing, it files private story_draft Proposals and raises one soft review request

  Scenario: monitor stories are off until switched on and never fail the run
    Given the stack parameter MonitorStoriesEnabled is "false", its default
    Then the execution goes from the trend drafts straight to Done and no monitor-stories task starts
    And when it is enabled and the step fails or times out, the execution still ends in Done
    And the failure is in the task log and the ledger row, and no Fail state, alarm or rollback follows from it

  Scenario: a site can list source hosts its AI drafts never cite
    Given the site's knowledgeRun block says excludedSourceHosts is ["ipwatchdog.com"]
    Then the task environment has KNOWLEDGE_EXCLUDED_SOURCE_HOSTS "ipwatchdog.com" and the trend-drafts and monitor-stories steps pass it to their commands as --exclude-host
    And a site without the setting gets no such variable, and a value that is not a list of bare lowercase host names is refused with the field named

  Scenario: the monitorStories setting is validated
    Then a limit below 1 or above 20, a limit that is not a whole number, an unknown field and a value that is not an object are all refused with the field named

  Scenario: a failing stage ends the execution in a Fail state
    Then each stage catches every error into its own Fail state
    And no stage continues into the next one after a failure, so projection never runs

  Scenario: the execution input drives the container environment
    Given an execution input of {"publication": "shipped", "failStage": "snapshot"} with both keys optional
    Then every task gets KNOWLEDGE_PUBLICATION from the input, defaulting to the configured publication
    And KNOWLEDGE_EXECUTION_NAME and KNOWLEDGE_EXECUTION_START from the execution context
    And KNOWLEDGE_FAIL_STAGE from the input, or an empty string

  Scenario: the container is one ARM64 image sized from config
    Then there is one task definition: Graviton ARM64, 4 vCPU, 16 GB, 40 GiB ephemeral storage
    And the container is named "job", logs with awslogs, and takes the image tag from the "imageTag" context
    And the static environment carries the state bucket, ledger table, lock table, site and role settings
    And computed variables win over the free-form environment map

  Scenario: the image repository is immutable and scanned
    Then the ECR repository "papyrus-scheduled-jobs/knowledge-run" scans on push, has immutable tags and keeps the last 10 images

  Scenario: the state bucket is private and expires old data
    Then the state bucket is versioned, SSE-S3 encrypted, SSL-only, blocks public access and is retained
    And it expires noncurrent versions after 90 days and the "runs/" prefix after 120 days

  Scenario: the run ledger is an on-demand table
    Then the ledger has partition key "publication", sort key "runKey", point-in-time recovery, TTL on "expiresAt" and is retained

  Scenario: a failed run alarms to SNS
    Then an alarm sums ExecutionsFailed, ExecutionsAborted and ExecutionsTimedOut over 5 minutes, filling gaps with zero
    And it alarms at 1 or more, treats missing data as not breaching, and notifies the SNS topic

  Scenario: a missed week alarms to SNS
    Then a daily watchdog Lambda publishes the days since the last successful execution, because CloudWatch cannot evaluate 8 days in one alarm
    And an alarm fires at 8 or more days and notifies the SNS topic
    And missing data breaches, so a dead watchdog or a week with no execution alarms
    And a new stack alarms (and notifies) until its first successful run, which is expected

  Scenario: the alarm e-mail comes from SSM and is never inline
    Then the e-mail subscription endpoint is a reference to an SSM String parameter named by config
    And no e-mail address appears anywhere in the template

  Scenario: a weekly schedule starts the state machine through a narrow role
    Then the schedule is "cron(0 5 ? * MON *)" in UTC with no flexible window and input {"publication":"shipped"}
    And its state and expression come from config
    And its role may only do states:StartExecution on the state machine

  Scenario: the task role is least privilege
    Then every action on the task role is named, with no wildcard actions and no "*" resource
    And the lock table is limited to GetItem, PutItem, UpdateItem and DeleteItem on its own ARN
    And the OpenAI key is read from an SSM parameter, never Secrets Manager
    And the template mentions Secrets Manager nowhere
    And appsync:GraphQL is limited to the Query and Mutation fields of the publication's API
    And the site bucket, distribution and key-value store are limited to the ARNs in config

  Scenario: the projection stages know the site's plugins
    Then the container environment carries PAPYRUS_PLUGINS from the site config
    And the task role may read the configuration of the site's content-actions Lambda and nothing else of Lambda

  Scenario: monitor records are opt-in and reach the container only when the site names a source
    Then the container has no KNOWLEDGE_MONITOR_SOURCES for the example config
    And the example config sets no monitorWeeks, so the container has no KNOWLEDGE_MONITOR_WEEKS and every monitor record counts
    And a knowledgeRun block with monitorSources "huggingface" and monitorWeeks 26 sets KNOWLEDGE_MONITOR_SOURCES and KNOWLEDGE_MONITOR_WEEKS
    And a knowledgeRun block with monitorSources "routed" sets KNOWLEDGE_MONITOR_SOURCES to "routed"
    And an empty, unknown or non-whole-week monitor setting is rejected naming "knowledgeRun.monitorSources" or "knowledgeRun.monitorWeeks"

  Scenario: the stages check out the commit the site runs
    Then the container environment names the CMS Amplify app
    And the task role may list the jobs of that app's branch and nothing else of Amplify

  Scenario: the shared lock table has its own stack
    Then stack "papyrus-projection-lock" holds table "papyrus-projection-locks" keyed by "publication" with TTL "expiresAt", on demand and retained
    And an SSM String parameter "/papyrus/projection-lock/table-name" holds the table name
    And the job stack holds no lock table

  Scenario: resources are tagged and the stacks are protected
    Then resources carry Project=Papyrus and Publication=shipped
    And the stack is named "papyrus-scheduled-job-knowledge-run-shipped"
    And both stacks have termination protection and the job stack outputs RepositoryUri, StateMachineArn, StateBucketName, LedgerTableName, AlarmTopicArn, ClusterName and TaskDefinitionArn

  Scenario: another pipeline reuses the construct
    Given a pipeline of two stages with different sizes, retries and environment
    When it is synthesized with the same construct
    Then it has a task definition per distinct size, its own repository name and its own stage order

  Scenario: invalid knowledgeRun config is rejected with the field name
    Given a knowledgeRun block with an unknown key, a missing site bucket, a bad KVS ARN, a bad vCPU, too little memory, a bad schedule or an unknown stage timeout
    Then validation fails naming the field, such as "knowledgeRun.siteBucket"
    And a site without a knowledgeRun block, or without aws.accountId and aws.region, is rejected
