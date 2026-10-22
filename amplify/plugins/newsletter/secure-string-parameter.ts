/**
 * A generated secret in SSM Parameter Store as a standard SecureString (never Secrets Manager).
 *
 * This is the same construct as `infra/amplify-app-shell/lib/secure-string-parameter.ts`, copied because the Papyrus npm
 * package ships `amplify/` but not `infra/` (the app-shell CDK app has its own tsconfig). Keep the two in step.
 * CloudFormation cannot create a SecureString, so a custom resource Lambda puts it: it generates the value, never returns
 * or logs it, never overwrites an existing parameter, and delete retains it. Readers get `ssm:GetParameter` on `parameterArn`
 * only; decrypting with the AWS-managed `aws/ssm` key needs no KMS grant.
 */
import { Construct } from "constructs";
import { ArnFormat, CustomResource, Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as customResources from "aws-cdk-lib/custom-resources";

export interface SecureStringParameterProps {
  /** Absolute parameter name, e.g. `/papyrus/<siteId>/prospectus-session-sealing`. */
  parameterName: string;
  description: string;
  /** Length of the generated value. Default 64. */
  length?: number;
}

/** Source of the Lambda behind SecureStringParameter, inline (CommonJS, under the 4096-character inline limit). */
export const SECURE_STRING_PARAMETER_HANDLER_SOURCE = `
const { randomInt } = require("node:crypto");
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
function generate(length) {
  let value = "";
  for (let index = 0; index < length; index += 1) value += ALPHABET[randomInt(ALPHABET.length)];
  return value;
}
exports.createHandler = (ssm, PutParameterCommand) => async (event) => {
  const name = event.ResourceProperties.ParameterName;
  if (event.RequestType === "Delete") return { PhysicalResourceId: event.PhysicalResourceId };
  try {
    await ssm.send(new PutParameterCommand({
      Name: name,
      Description: event.ResourceProperties.Description,
      Type: "SecureString",
      Tier: "Standard",
      Overwrite: false,
      Value: generate(Number(event.ResourceProperties.Length)),
    }));
  } catch (error) {
    if (!error || error.name !== "ParameterAlreadyExists") {
      throw new Error("PutParameter failed for " + name + " (" + (error && error.name ? error.name : "error") + ")");
    }
  }
  return { PhysicalResourceId: name };
};
exports.handler = async (event) => {
  const { SSMClient, PutParameterCommand } = require("@aws-sdk/client-ssm");
  return exports.createHandler(new SSMClient({}), PutParameterCommand)(event);
};
`;

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
