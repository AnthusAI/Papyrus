// Pre-token-generation Lambda, V2 event (spike PPY-867f76). The membership table is hard-coded on purpose.
// Test users are Google-federated Cognito users, identified by email; the acting tenant comes from the sign-in request's
// clientMetadata or, when absent, the user's first membership. Claims go on the ACCESS token, which is what the
// Amplify v6 data client sends for userPool auth.
const MEMBERSHIPS = {
  // email placeholder -> tenant -> role. Real test addresses are kept out of the repo (AWS config / env).
  "alpha-editor@example.test": { alpha: "editor" },
  "beta-editor@example.test": { beta: "editor" },
};
const ROLE_CLAIM = (role) => `papyrus_tenant_${role}`;

exports.handler = async (event) => {
  const email = event.request.userAttributes.email;
  const memberships = MEMBERSHIPS[email] ?? {};
  const wanted = event.request.clientMetadata?.tenant;
  const tenant = wanted && memberships[wanted] ? wanted : Object.keys(memberships)[0];
  if (tenant) {
    const claim = ROLE_CLAIM(memberships[tenant]);
    event.response = {
      claimsAndScopeOverrideDetails: {
        accessTokenGeneration: { claimsToAddOrOverride: { [claim]: tenant } },
        idTokenGeneration: { claimsToAddOrOverride: { [claim]: tenant } },
      },
    };
  }
  return event;
};
