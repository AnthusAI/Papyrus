import { Construct } from "constructs";
import { ArnFormat, CustomResource, Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as customResources from "aws-cdk-lib/custom-resources";
import { SECURE_STRING_PARAMETER_HANDLER_SOURCE } from "./secure-string-parameter-handler";

export interface SecureStringParameterProps {
  /** Absolute parameter name, e.g. `/papyrus/<siteId>/prospectus-session-sealing`. */
  parameterName: string;
  description: string;
  /** Length of the generated value. Default 64. */
  length?: number;
}

/** One Lambda and role per stack, shared by every SecureStringParameter in it. */
class SecureStringParameterProvider extends Construct {
  static readonly ID = "SecureStringParameterProvider";
  public readonly role: iam.Role;
  public readonly provider: customResources.Provider;

  static of(stack: Stack): SecureStringParameterProvider {
    return (stack.node.tryFindChild(SecureStringParameterProvider.ID) as SecureStringParameterProvider | undefined)
      ?? new SecureStringParameterProvider(stack);
  }

  private constructor(stack: Stack) {
    super(stack, SecureStringParameterProvider.ID);
    this.role = new iam.Role(this, "Role", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Creates generated SecureString parameters: PutParameter per named parameter, never overwriting",
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole")],
    });
    const onEvent = new lambda.Function(this, "OnEvent", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(SECURE_STRING_PARAMETER_HANDLER_SOURCE),
      role: this.role,
      timeout: Duration.seconds(30),
      description: "Creates a generated SecureString parameter once; never returns or logs the value",
    });
    this.provider = new customResources.Provider(this, "Provider", { onEventHandler: onEvent });
  }
}

/**
 * A generated secret in SSM Parameter Store as a standard SecureString (free,
 * AWS-managed `aws/ssm` key), instead of a Secrets Manager secret ($0.40/month).
 *
 * CloudFormation cannot create a SecureString, so a custom resource Lambda puts
 * it. The Lambda generates a random value at create time and never returns or
 * logs it, so the value is in no template, output or stack event. It is
 * create-only: an update never regenerates it and never overwrites a parameter
 * that already exists (a hand-made one is adopted as it is), and delete retains
 * it, so a stack teardown cannot sign anyone out. Rotate it with
 * `aws ssm put-parameter --overwrite`. Readers get `ssm:GetParameter` on
 * `parameterArn` only; decrypting with the AWS-managed key needs no KMS grant.
 */
export class SecureStringParameter extends Construct {
  public readonly parameterName: string;
  public readonly parameterArn: string;

  constructor(scope: Construct, id: string, props: SecureStringParameterProps) {
    super(scope, id);
    if (!props.parameterName.startsWith("/")) throw new Error(`SSM parameter name must be absolute: ${props.parameterName}`);
    const length = props.length ?? 64;
    if (!Number.isInteger(length) || length < 32) throw new Error("A generated secret must be at least 32 characters.");
    const stack = Stack.of(this);
    this.parameterName = props.parameterName;
    this.parameterArn = stack.formatArn({
      service: "ssm",
      resource: "parameter",
      resourceName: props.parameterName.slice(1),
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    });

    const shared = SecureStringParameterProvider.of(stack);
    shared.role.addToPolicy(new iam.PolicyStatement({
      sid: `Put${id.replace(/[^A-Za-z0-9]/g, "")}`,
      actions: ["ssm:PutParameter"],
      resources: [this.parameterArn],
    }));
    const resource = new CustomResource(this, "Resource", {
      serviceToken: shared.provider.serviceToken,
      resourceType: "Custom::SecureStringParameter",
      properties: { ParameterName: props.parameterName, Description: props.description, Length: String(length) },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    resource.node.addDependency(shared.role);
  }
}
