const fs = require("node:fs");
const path = require("node:path");

function loadDotEnv() {
  for (const filename of [".env", ".env.local"]) {
    const filepath = path.join(process.cwd(), filename);
    if (!fs.existsSync(filepath)) continue;

    for (const line of fs.readFileSync(filepath, "utf8").split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const equalsIndex = trimmed.indexOf("=");
      if (equalsIndex === -1) continue;
      const key = trimmed.slice(0, equalsIndex).trim();
      const rawValue = trimmed.slice(equalsIndex + 1).trim();
      if (!key || process.env[key] !== undefined) continue;
      process.env[key] = unquote(rawValue);
    }
  }
}

function getRequiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable ${name}.`);
  }
  return value;
}

function getGraphQLEndpoint() {
  if (process.env.PAPYRUS_GRAPHQL_ENDPOINT) {
    return process.env.PAPYRUS_GRAPHQL_ENDPOINT;
  }

  const outputsPath = getAmplifyOutputsPath();
  if (!fs.existsSync(outputsPath)) {
    throw new Error("Missing PAPYRUS_GRAPHQL_ENDPOINT and amplify_outputs.json.");
  }

  const outputs = loadAmplifyOutputs();
  const endpoint = outputs?.data?.url ?? outputs?.aws_appsync_graphqlEndpoint;
  if (!endpoint) {
    throw new Error("Could not determine GraphQL endpoint from amplify_outputs.json.");
  }
  return endpoint;
}

function getJwtToken() {
  const rawToken = process.env.PAPYRUS_GRAPHQL_JWT;
  if (!rawToken) {
    throw new Error("Missing PAPYRUS_GRAPHQL_JWT. Set a direct AppSync Lambda-authorizer authoring JWT before running content CLI commands.");
  }
  return normalizeJwt(rawToken);
}

function hasAmplifyOutputs() {
  return fs.existsSync(getAmplifyOutputsPath());
}

function loadAmplifyOutputs() {
  const outputsPath = getAmplifyOutputsPath();
  if (!fs.existsSync(outputsPath)) {
    throw new Error("Missing amplify_outputs.json. Run `npm run sandbox` or deploy the Amplify backend first.");
  }

  return JSON.parse(fs.readFileSync(outputsPath, "utf8"));
}

function getAmplifyOutputsPath() {
  return path.join(process.cwd(), "amplify_outputs.json");
}

function normalizeJwt(token) {
  return token.replace(/^Bearer\s+/i, "").trim();
}

function decodeJwtClaims(token) {
  const normalized = normalizeJwt(token);
  const parts = normalized.split(".");
  if (parts.length < 2) {
    throw new Error("PAPYRUS_GRAPHQL_JWT is not a valid JWT.");
  }

  try {
    const payload = parts[1]
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(parts[1].length / 4) * 4, "=");
    return JSON.parse(Buffer.from(payload, "base64").toString("utf8"));
  } catch {
    throw new Error("PAPYRUS_GRAPHQL_JWT is not a valid JWT.");
  }
}

function isJwtExpired(claims) {
  if (typeof claims.exp !== "number") return false;
  return claims.exp * 1000 <= Date.now();
}

function unquote(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

module.exports = {
  decodeJwtClaims,
  getGraphQLEndpoint,
  getJwtToken,
  hasAmplifyOutputs,
  isJwtExpired,
  loadAmplifyOutputs,
  loadDotEnv,
  normalizeJwt,
};
