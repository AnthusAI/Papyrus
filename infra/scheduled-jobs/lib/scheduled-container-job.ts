import { CfnOutput, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cwActions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subs from "aws-cdk-lib/aws-sns-subscriptions";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

export type StageRetry = { maxAttempts: number; intervalSeconds: number; backoffRate: number };

/** One step of a pipeline: a single Fargate task running `command` in the job's container image. */
export type StageDefinition = {
  name: string;
  command: string[];
  vCpu?: number;
  memoryMiB?: number;
  ephemeralStorageGiB?: number;
  timeoutSeconds?: number;
  retry?: Partial<StageRetry>;
  /** Extra container environment for this stage only. */
  environment?: Record<string, string>;
};

export type PipelineDefinition = {
  /** Stages run strictly in this order; a stage failing after its retries ends the execution in a Fail state. */
  stages: StageDefinition[];
  /**
   * Per-execution container environment: variable name to a JSONata expression (no `{% %}` wrapper). Evaluated by
   * Step Functions for every stage, against `$states.context` (the execution input, name and start time).
   */
  executionEnvironment?: Record<string, string>;
};

export type ScheduledContainerJobProps = {
  /** Short id of the job kind, such as `knowledge-run`. Names the ECR repository and the schedule. */
  jobId: string;
  publication: string;
  pipeline: PipelineDefinition;
  /** ECR image tag. The repository is created by this construct, so the first deploy can use a placeholder. */
  imageTag: string;
  /** Default task size for stages that do not set their own. */
  defaultSize: { vCpu: number; memoryMiB: number; ephemeralStorageGiB: number };
  defaultStageTimeoutSeconds: number;
  defaultRetry?: Partial<StageRetry>;
  /** EventBridge Scheduler expression and state. The execution input is `scheduleInput`. */
  schedule: { expression: string; state: "ENABLED" | "DISABLED" };
  scheduleInput: Record<string, unknown>;
  /** Static container environment. */
  environment: Record<string, string>;
  /** Environment variable names that receive the state bucket and ledger table names. */
  stateBucketEnvVar: string;
  ledgerTableEnvVar: string;
  /** Extra statements for the task role (config-driven access to the site, secrets, other tables). */
  taskPolicyStatements: iam.PolicyStatement[];
  /** SSM String parameter holding the alarm e-mail address. The address is never in the template or the code. */
  alarmEmailParameter: string;
};

const RETRY_DEFAULTS: StageRetry = { maxAttempts: 2, intervalSeconds: 60, backoffRate: 2 };
const RETRYABLE_ERRORS = ["States.TaskFailed", "ECS.AmazonECSException", "ECS.ServerException", "ECS.ClientException"];
const MISSED_WEEK_DAYS = 8;

/**
 * A weekly (or any schedule) container job: EventBridge Scheduler starts a Standard Step Functions state machine
 * whose states are Fargate tasks (`ecs:runTask.sync`) from one image, in a public-subnet VPC with no NAT gateway,
 * with a state bucket, a run ledger table, a least-privilege task role and failure / missed-run alarms to SNS.
 */
export class ScheduledContainerJob extends Construct {
  readonly vpc: ec2.Vpc;
  readonly securityGroup: ec2.SecurityGroup;
  readonly cluster: ecs.Cluster;
  readonly repository: ecr.Repository;
  readonly stateBucket: s3.Bucket;
  readonly ledgerTable: dynamodb.Table;
  readonly taskRole: iam.Role;
  readonly taskDefinition: ecs.FargateTaskDefinition;
  readonly stateMachine: sfn.StateMachine;
  readonly alarmTopic: sns.Topic;
  readonly failureAlarm: cloudwatch.Alarm;
  readonly missedWeekAlarm: cloudwatch.Alarm;
  readonly schedule: scheduler.CfnSchedule;

  constructor(scope: Construct, id: string, props: ScheduledContainerJobProps) {
    super(scope, id);
    if (props.pipeline.stages.length === 0) throw new Error("a pipeline needs at least one stage");
    const names = props.pipeline.stages.map((stage) => stage.name);
    if (new Set(names).size !== names.length) throw new Error(`pipeline stage names must be unique: ${names.join(", ")}`);

    // Public subnets only, no NAT gateway: tasks get a public IP for egress, the security group admits nothing.
    this.vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [{ name: "public", subnetType: ec2.SubnetType.PUBLIC, mapPublicIpOnLaunch: true }],
      gatewayEndpoints: {
        S3: { service: ec2.GatewayVpcEndpointAwsService.S3 },
        DynamoDb: { service: ec2.GatewayVpcEndpointAwsService.DYNAMODB },
      },
    });
    this.securityGroup = new ec2.SecurityGroup(this, "TaskSecurityGroup", {
      vpc: this.vpc,
      description: `Egress-only security group for the ${props.jobId} tasks of ${props.publication}`,
      allowAllOutbound: true,
    });
    this.cluster = new ecs.Cluster(this, "Cluster", { vpc: this.vpc });

    this.repository = new ecr.Repository(this, "Repository", {
      repositoryName: `papyrus-scheduled-jobs/${props.jobId}`,
      imageScanOnPush: true,
      imageTagMutability: ecr.TagMutability.IMMUTABLE,
      lifecycleRules: [{ maxImageCount: 10, description: "Keep the last 10 images" }],
      removalPolicy: RemovalPolicy.RETAIN,
    });

    this.stateBucket = new s3.Bucket(this, "StateBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: RemovalPolicy.RETAIN,
      lifecycleRules: [
        { id: "expire-noncurrent-versions", noncurrentVersionExpiration: Duration.days(90) },
        { id: "expire-runs", prefix: "runs/", expiration: Duration.days(120) },
      ],
    });

    this.ledgerTable = new dynamodb.Table(this, "LedgerTable", {
      partitionKey: { name: "publication", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "runKey", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      timeToLiveAttribute: "expiresAt",
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const taskLogGroup = new logs.LogGroup(this, "TaskLogGroup", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    this.taskRole = new iam.Role(this, "TaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: `Task role of the ${props.jobId} job for ${props.publication}`,
    });
    this.taskRole.addToPolicy(new iam.PolicyStatement({
      sid: "StateBucketObjects",
      actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      resources: [this.stateBucket.arnForObjects("*")],
    }));
    this.taskRole.addToPolicy(new iam.PolicyStatement({
      sid: "StateBucketList",
      actions: ["s3:ListBucket", "s3:GetBucketLocation"],
      resources: [this.stateBucket.bucketArn],
    }));
    this.taskRole.addToPolicy(new iam.PolicyStatement({
      sid: "LedgerTable",
      actions: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"],
      resources: [this.ledgerTable.tableArn],
    }));
    for (const statement of props.taskPolicyStatements) this.taskRole.addToPolicy(statement);

    const environment: Record<string, string> = {
      ...props.environment,
      [props.stateBucketEnvVar]: this.stateBucket.bucketName,
      [props.ledgerTableEnvVar]: this.ledgerTable.tableName,
    };

    // One task definition per distinct task size; a pipeline whose stages share the default size has exactly one.
    const taskDefinitions = new Map<string, ecs.FargateTaskDefinition>();
    const taskDefinitionFor = (stage: StageDefinition): ecs.FargateTaskDefinition => {
      const vCpu = stage.vCpu ?? props.defaultSize.vCpu;
      const memoryMiB = stage.memoryMiB ?? props.defaultSize.memoryMiB;
      const ephemeralStorageGiB = stage.ephemeralStorageGiB ?? props.defaultSize.ephemeralStorageGiB;
      const key = `${vCpu}-${memoryMiB}-${ephemeralStorageGiB}`;
      const existing = taskDefinitions.get(key);
      if (existing) return existing;
      const definition = new ecs.FargateTaskDefinition(this, taskDefinitions.size === 0 ? "TaskDefinition" : `TaskDefinition${key}`, {
        cpu: vCpu * 1024,
        memoryLimitMiB: memoryMiB,
        ephemeralStorageGiB,
        runtimePlatform: { cpuArchitecture: ecs.CpuArchitecture.ARM64, operatingSystemFamily: ecs.OperatingSystemFamily.LINUX },
        taskRole: this.taskRole,
      });
      definition.addContainer("job", {
        containerName: "job",
        image: ecs.ContainerImage.fromEcrRepository(this.repository, props.imageTag),
        environment,
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: props.jobId, logGroup: taskLogGroup }),
      });
      taskDefinitions.set(key, definition);
      return definition;
    };

    const retryDefaults = { ...RETRY_DEFAULTS, ...props.defaultRetry };
    const executionEnvironment = Object.entries(props.pipeline.executionEnvironment ?? {}).map(([name, expression]) => ({
      name,
      value: `{% ${expression} %}`,
    }));
    const failStates: sfn.Fail[] = [];
    const taskStates = props.pipeline.stages.map((stage) => {
      const retry = { ...retryDefaults, ...stage.retry };
      const state = tasks.EcsRunTask.jsonata(this, stage.name, {
        stateName: stage.name,
        integrationPattern: sfn.IntegrationPattern.RUN_JOB,
        cluster: this.cluster,
        taskDefinition: taskDefinitionFor(stage),
        launchTarget: new tasks.EcsFargateLaunchTarget({ platformVersion: ecs.FargatePlatformVersion.LATEST }),
        assignPublicIp: true,
        subnets: { subnetType: ec2.SubnetType.PUBLIC },
        securityGroups: [this.securityGroup],
        containerOverrides: [{
          containerDefinition: taskDefinitionFor(stage).findContainer("job") as ecs.ContainerDefinition,
          command: stage.command,
          environment: [
            ...executionEnvironment,
            ...Object.entries(stage.environment ?? {}).map(([name, value]) => ({ name, value })),
          ],
        }],
        taskTimeout: sfn.Timeout.duration(Duration.seconds(stage.timeoutSeconds ?? props.defaultStageTimeoutSeconds)),
      });
      state.addRetry({
        errors: RETRYABLE_ERRORS,
        maxAttempts: retry.maxAttempts,
        interval: Duration.seconds(retry.intervalSeconds),
        backoffRate: retry.backoffRate,
        jitterStrategy: sfn.JitterType.FULL,
      });
      const failed = sfn.Fail.jsonata(this, `Failed-${stage.name}`, {
        stateName: `Failed-${stage.name}`,
        error: "StageFailed",
        cause: `Stage ${stage.name} failed after its retries; later stages did not run.`,
      });
      failStates.push(failed);
      state.addCatch(failed, { errors: [sfn.Errors.ALL] });
      return state;
    });
    const done = sfn.Succeed.jsonata(this, "Done", { stateName: "Done" });
    taskStates.forEach((state, index) => state.next(index + 1 < taskStates.length ? taskStates[index + 1] : done));

    const stateMachineLogs = new logs.LogGroup(this, "StateMachineLogGroup", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    this.stateMachine = new sfn.StateMachine(this, "StateMachine", {
      stateMachineType: sfn.StateMachineType.STANDARD,
      queryLanguage: sfn.QueryLanguage.JSONATA,
      definitionBody: sfn.DefinitionBody.fromChainable(sfn.Chain.start(taskStates[0])),
      logs: { destination: stateMachineLogs, level: sfn.LogLevel.ERROR },
      tracingEnabled: false,
    });
    this.taskDefinition = taskDefinitions.values().next().value as ecs.FargateTaskDefinition;

    // Weekly schedule. Its role may do nothing but start this state machine.
    const scheduleRole = new iam.Role(this, "ScheduleRole", { assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com") });
    scheduleRole.addToPolicy(new iam.PolicyStatement({ actions: ["states:StartExecution"], resources: [this.stateMachine.stateMachineArn] }));
    this.schedule = new scheduler.CfnSchedule(this, "Schedule", {
      description: `${props.jobId} for ${props.publication}`,
      scheduleExpression: props.schedule.expression,
      scheduleExpressionTimezone: "UTC",
      state: props.schedule.state,
      flexibleTimeWindow: { mode: "OFF" },
      target: {
        arn: this.stateMachine.stateMachineArn,
        roleArn: scheduleRole.roleArn,
        input: JSON.stringify(props.scheduleInput),
        retryPolicy: { maximumRetryAttempts: 2, maximumEventAgeInSeconds: 3600 },
      },
    });

    // Alarms. The address comes from an SSM String parameter resolved by CloudFormation at deploy time.
    this.alarmTopic = new sns.Topic(this, "AlarmTopic", { displayName: `${props.jobId} ${props.publication}` });
    this.alarmTopic.addSubscription(new subs.EmailSubscription(ssm.StringParameter.valueForStringParameter(this, props.alarmEmailParameter)));
    const alarmAction = new cwActions.SnsAction(this.alarmTopic);

    // Step Functions emits a failure metric only when something fails, so each series is filled with 0.
    const fiveMinutes = { period: Duration.minutes(5), statistic: "Sum" };
    this.failureAlarm = new cloudwatch.Alarm(this, "FailureAlarm", {
      alarmDescription: `A ${props.jobId} execution for ${props.publication} failed, timed out or was aborted.`,
      metric: new cloudwatch.MathExpression({
        expression: "FILL(failed, 0) + FILL(aborted, 0) + FILL(timedOut, 0)",
        period: Duration.minutes(5),
        usingMetrics: {
          failed: this.stateMachine.metricFailed(fiveMinutes),
          aborted: this.stateMachine.metricAborted(fiveMinutes),
          timedOut: this.stateMachine.metricTimedOut(fiveMinutes),
        },
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    this.failureAlarm.addAlarmAction(alarmAction);

    // Missed week: no successful execution on any of the last 8 days. Missing data breaches, so a week with no
    // execution at all alarms. For the same reason this alarm goes to ALARM (and notifies) when the stack is new,
    // until the first successful run is more recent than 8 days; that is expected.
    this.missedWeekAlarm = new cloudwatch.Alarm(this, "MissedWeekAlarm", {
      alarmDescription: `No successful ${props.jobId} execution for ${props.publication} in ${MISSED_WEEK_DAYS} days.`,
      metric: this.stateMachine.metricSucceeded({ period: Duration.days(1), statistic: "Sum" }),
      threshold: 1,
      evaluationPeriods: MISSED_WEEK_DAYS,
      datapointsToAlarm: MISSED_WEEK_DAYS,
      comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.BREACHING,
    });
    this.missedWeekAlarm.addAlarmAction(alarmAction);
  }

  /** Publishes the standard outputs on `scope` (normally the stack), with plain logical ids. */
  addOutputs(scope: Construct): void {
    for (const [name, value] of Object.entries({
      RepositoryUri: this.repository.repositoryUri,
      StateMachineArn: this.stateMachine.stateMachineArn,
      StateBucketName: this.stateBucket.bucketName,
      LedgerTableName: this.ledgerTable.tableName,
      AlarmTopicArn: this.alarmTopic.topicArn,
      ClusterName: this.cluster.clusterName,
      TaskDefinitionArn: this.taskDefinition.taskDefinitionArn,
    })) {
      new CfnOutput(scope, name, { value });
    }
  }
}
