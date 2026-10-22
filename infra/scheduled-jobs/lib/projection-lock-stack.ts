import { CfnOutput, RemovalPolicy, Stack, StackProps, Tags } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

/** The projection lease table is shared by every publication in the account; its name is fixed so job stacks need no cross-stack reference. */
export const PROJECTION_LOCK_TABLE_NAME = "papyrus-projection-locks";
export const PROJECTION_LOCK_STACK_NAME = "papyrus-projection-lock";
export const PROJECTION_LOCK_PARAMETER_NAME = "/papyrus/projection-lock/table-name";

export class ProjectionLockStack extends Stack {
  readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, { stackName: PROJECTION_LOCK_STACK_NAME, terminationProtection: true, ...props });
    Tags.of(this).add("Project", "Papyrus");

    this.table = new dynamodb.Table(this, "LockTable", {
      tableName: PROJECTION_LOCK_TABLE_NAME,
      partitionKey: { name: "publication", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expiresAt",
      removalPolicy: RemovalPolicy.RETAIN,
    });
    new ssm.StringParameter(this, "TableNameParameter", {
      parameterName: PROJECTION_LOCK_PARAMETER_NAME,
      stringValue: this.table.tableName,
      description: "Name of the shared Papyrus projection lease table",
    });
    new CfnOutput(this, "LockTableName", { value: this.table.tableName });
  }
}
