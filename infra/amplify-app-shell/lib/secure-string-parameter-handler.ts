/**
 * Source of the Lambda behind SecureStringParameter, as a string so the staged
 * package (which ships only .ts under infra/) can inline it and tests can run it
 * against a fake SSM client. CommonJS, under the 4096-character inline limit.
 *
 * It creates the parameter when it is missing and does nothing else: it never
 * overwrites an existing value, never reads one back, never logs the value, and
 * returns no data (only the parameter name as the physical id).
 */
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
