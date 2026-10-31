// Prospectus authorize, the first function of every account-scoped mutation's pipeline. Fail closed: the next function runs only
// when Prospectus has just said this person may write to the account named in X-Prospectus-Account. The HTTP data source signs
// the request (SigV4, execute-api). Pool groups alone are not authorization. The same rules as lib/prospectus-authorize.ts.
import { runtime, util } from "@aws-appsync/utils";

const STAGE_PATH = "/api";
const ACCOUNT_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-";
const MARKERS = ["cognitoIdentityId", "cognitoIdentityPoolId", "cognitoIdentityAuthType", "sub", "claims"];

function validAccount(account) {
  if (account.length < 1 || account.length > 64) return false;
  for (const character of account.split("")) {
    if (ACCOUNT_CHARACTERS.indexOf(character) < 0) return false;
  }
  return true;
}

function isSiteFunctionCaller(identity) {
  if (!identity || !identity.accountId || typeof identity.userArn !== "string") return false;
  const parts = identity.userArn.split(":");
  if (parts.length < 6 || parts[0] !== "arn" || parts[4] !== identity.accountId) return false;
  for (const marker of MARKERS) {
    if (identity[marker]) return false;
  }
  return true;
}

export function request(ctx) {
  if (isSiteFunctionCaller(ctx.identity)) runtime.earlyReturn({});
  const headers = ctx.request.headers;
  const account = typeof headers["x-prospectus-account"] === "string" ? headers["x-prospectus-account"].trim() : "";
  if (!account) util.error("account_required", "AccountRequired");
  const token = headers["x-prospectus-human-token"];
  if (!token || !validAccount(account)) util.unauthorized();
  ctx.stash.prospectusAccount = account;
  return {
    method: "POST",
    resourcePath: STAGE_PATH + "/v1/accounts/" + account + "/authorize",
    params: {
      headers: { "content-type": "application/json", "x-prospectus-human-token": token },
      body: JSON.stringify({ operation: "console:write" }),
    },
  };
}

export function response(ctx) {
  if (ctx.error) util.unauthorized();
  const status = ctx.result.statusCode;
  const answer = ctx.result.body ? JSON.parse(ctx.result.body) : {};
  if ((status === 401 || status === 403) && answer.error === "reenrollment_required") {
    util.error("reenrollment_required", "ReenrollmentRequired");
  }
  if (status !== 200 || answer.allowed !== true || answer.accountId !== ctx.stash.prospectusAccount) util.unauthorized();
  return {};
}
