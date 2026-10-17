/*
 * <papyrus-signup>: an email signup form for a static Papyrus site.
 *
 * Framework-free and dependency-free. Include it once with
 *   <script src="/_plugins/papyrus-signup@1.js" defer></script>
 * and place the element anywhere in a page:
 *   <papyrus-signup form="newsletter"
 *     endpoint="https://<id>.appsync-api.<region>.amazonaws.com/graphql"
 *     identity-pool="<region>:<uuid>"></papyrus-signup>
 *
 * Attributes
 *   form           which signup list; must be one the site's backend accepts   required
 *   endpoint       the site's GraphQL endpoint (amplify_outputs.json data.url)   required*
 *   identity-pool  the site's Cognito identity pool id                           required*
 *   region         AWS region                                                   default: from the pool id
 *   label          accessible name of the input                                 default "Email address"
 *   button         button text                                                  default "Sign up"
 *   success        message after a submission                                   default "Thank you. You are on the list."
 *   (*) or set once for the whole site: window.papyrusSignup = { endpoint, identityPool, region }
 *
 * The page signs its one request as the pool's unauthenticated identity. That identity can call
 * submitSignup and nothing that reads data back. Styling hooks (the element renders into its own
 * light DOM): form.papyrus-signup, label.papyrus-signup-label, input.papyrus-signup-input,
 * button.papyrus-signup-button, p.papyrus-signup-status[data-state]. Every status is words, never
 * colour alone. A "papyrus-signup" event with detail.status fires on the element after each attempt.
 * Without JavaScript the element is empty and the page is unchanged.
 */
(function () {
  "use strict";

  var MUTATION =
    "mutation SubmitSignup($form: String!, $value: String!, $renderedAt: String!, $website: String) {" +
    " submitSignup(form: $form, value: $value, renderedAt: $renderedAt, website: $website) { status message } }";
  var MESSAGES = {
    invalid: "Error: please enter a valid email address.",
    expired: "Error: this form has expired. Reload the page and try again.",
    throttled: "Error: too many attempts. Wait a minute and try again.",
    failed: "Error: something went wrong. Please try again later.",
    unconfigured: "Error: this form is not set up."
  };
  var encoder = new TextEncoder();

  function toHex(buffer) {
    return Array.prototype.map.call(new Uint8Array(buffer), function (byte) {
      return ("0" + byte.toString(16)).slice(-2);
    }).join("");
  }

  function sha256Hex(text) {
    return crypto.subtle.digest("SHA-256", encoder.encode(text)).then(toHex);
  }

  function hmac(keyBytes, text) {
    return crypto.subtle
      .importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
      .then(function (key) { return crypto.subtle.sign("HMAC", key, encoder.encode(text)); });
  }

  function signingKey(secret, dateStamp, region, service) {
    return hmac(encoder.encode("AWS4" + secret), dateStamp)
      .then(function (dateKey) { return hmac(dateKey, region); })
      .then(function (regionKey) { return hmac(regionKey, service); })
      .then(function (serviceKey) { return hmac(serviceKey, "aws4_request"); });
  }

  /* Signs a JSON POST with SigV4. Resolves with the headers to send (Host is added by the browser). */
  function sign(request) {
    var url = new URL(request.url);
    var amzDate = request.date.toISOString().replace(/[:-]|\.\d{3}/g, "");
    var dateStamp = amzDate.slice(0, 8);
    var headers = {
      "content-type": "application/json",
      host: url.host,
      "x-amz-date": amzDate,
      "x-amz-security-token": request.credentials.sessionToken
    };
    var names = Object.keys(headers).sort();
    var canonicalHeaders = names.map(function (name) { return name + ":" + headers[name] + "\n"; }).join("");
    var signedHeaders = names.join(";");
    return sha256Hex(request.body).then(function (payloadHash) {
      var canonicalRequest = ["POST", url.pathname, "", canonicalHeaders, signedHeaders, payloadHash].join("\n");
      var scope = dateStamp + "/" + request.region + "/" + request.service + "/aws4_request";
      return sha256Hex(canonicalRequest).then(function (requestHash) {
        var stringToSign = ["AWS4-HMAC-SHA256", amzDate, scope, requestHash].join("\n");
        return signingKey(request.credentials.secretKey, dateStamp, request.region, request.service)
          .then(function (key) { return hmac(key, stringToSign); })
          .then(function (signature) {
            return {
              "content-type": headers["content-type"],
              "x-amz-date": amzDate,
              "x-amz-security-token": headers["x-amz-security-token"],
              authorization:
                "AWS4-HMAC-SHA256 Credential=" + request.credentials.accessKeyId + "/" + scope +
                ", SignedHeaders=" + signedHeaders + ", Signature=" + toHex(signature)
            };
          });
      });
    });
  }

  function cognito(region, target, payload) {
    return fetch("https://cognito-identity." + region + ".amazonaws.com/", {
      method: "POST",
      headers: { "content-type": "application/x-amz-json-1.1", "x-amz-target": "AWSCognitoIdentityService." + target },
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (!response.ok) throw new Error("identity " + response.status);
      return response.json();
    });
  }

  var credentialsByPool = {};

  function guestCredentials(pool, region) {
    var cached = credentialsByPool[pool];
    if (cached && cached.expiresAt - Date.now() > 60000) return Promise.resolve(cached.credentials);
    var storageKey = "papyrus-signup-identity:" + pool;
    var identityId = null;
    try { identityId = window.localStorage.getItem(storageKey); } catch (error) { identityId = null; }
    var identity = identityId
      ? Promise.resolve(identityId)
      : cognito(region, "GetId", { IdentityPoolId: pool }).then(function (body) {
          try { window.localStorage.setItem(storageKey, body.IdentityId); } catch (error) { /* storage is optional */ }
          return body.IdentityId;
        });
    return identity
      .then(function (id) { return cognito(region, "GetCredentialsForIdentity", { IdentityId: id }); })
      .then(function (body) {
        var raw = body.Credentials;
        var credentials = { accessKeyId: raw.AccessKeyId, secretKey: raw.SecretKey, sessionToken: raw.SessionToken };
        credentialsByPool[pool] = { credentials: credentials, expiresAt: raw.Expiration * 1000 };
        return credentials;
      });
  }

  function submit(settings, form, value, renderedAt, honeypot) {
    var body = JSON.stringify({
      query: MUTATION,
      variables: { form: form, value: value, renderedAt: String(renderedAt), website: honeypot }
    });
    return guestCredentials(settings.identityPool, settings.region).then(function (credentials) {
      return sign({
        url: settings.endpoint, body: body, date: new Date(), region: settings.region, service: "appsync", credentials: credentials
      }).then(function (headers) {
        return fetch(settings.endpoint, { method: "POST", headers: headers, body: body });
      });
    }).then(function (response) {
      if (response.status === 429 || response.status === 403 && response.headers.get("x-amzn-waf-action")) {
        return { status: "throttled" };
      }
      return response.json().then(function (payload) {
        var receipt = payload && payload.data && payload.data.submitSignup;
        return receipt ? { status: receipt.status } : { status: "failed" };
      });
    });
  }

  function siteSettings() {
    return window.papyrusSignup || {};
  }

  function element(tag, className, attributes) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    Object.keys(attributes || {}).forEach(function (name) { node.setAttribute(name, attributes[name]); });
    return node;
  }

  var counter = 0;

  var Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

  class PapyrusSignup extends Base {
    connectedCallback() {
      if (this.firstChild) return;
      counter += 1;
      var site = siteSettings();
      var identityPool = this.getAttribute("identity-pool") || site.identityPool || "";
      this.settings = {
        endpoint: this.getAttribute("endpoint") || site.endpoint || "",
        identityPool: identityPool,
        region: this.getAttribute("region") || site.region || identityPool.split(":")[0]
      };
      this.formName = this.getAttribute("form") || "";
      this.renderedAt = Date.now();
      var inputId = "papyrus-signup-" + counter;
      var form = element("form", "papyrus-signup", { novalidate: "" });
      var label = element("label", "papyrus-signup-label", { for: inputId });
      label.textContent = this.getAttribute("label") || "Email address";
      this.input = element("input", "papyrus-signup-input", {
        id: inputId, type: "email", name: "email", required: "", maxlength: "254", autocomplete: "email"
      });
      var trap = element("div", "", { "aria-hidden": "true", style: "position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden" });
      this.trap = element("input", "", { type: "text", name: "website", tabindex: "-1", autocomplete: "off" });
      trap.appendChild(this.trap);
      this.button = element("button", "papyrus-signup-button", { type: "submit" });
      this.button.textContent = this.getAttribute("button") || "Sign up";
      this.status = element("p", "papyrus-signup-status", { role: "status", "aria-live": "polite" });
      form.appendChild(label);
      form.appendChild(this.input);
      form.appendChild(trap);
      form.appendChild(this.button);
      form.appendChild(this.status);
      form.addEventListener("submit", this.onSubmit.bind(this));
      this.appendChild(form);
    }

    show(state, text) {
      this.status.setAttribute("data-state", state);
      this.status.textContent = text;
      this.dispatchEvent(new CustomEvent("papyrus-signup", { detail: { status: state } }));
    }

    onSubmit(event) {
      event.preventDefault();
      var value = this.input.value.trim();
      if (!value || !this.input.checkValidity()) return this.show("invalid", MESSAGES.invalid);
      if (!this.settings.endpoint || !this.settings.identityPool || !this.formName) return this.show("unconfigured", MESSAGES.unconfigured);
      this.button.disabled = true;
      this.status.removeAttribute("data-state");
      this.status.textContent = "Sending...";
      var self = this;
      submit(this.settings, this.formName, value, this.renderedAt, this.trap.value)
        .catch(function () { return { status: "failed" }; })
        .then(function (outcome) {
          self.button.disabled = false;
          if (outcome.status === "accepted") {
            self.input.value = "";
            return self.show("accepted", self.getAttribute("success") || "Thank you. You are on the list.");
          }
          self.show(outcome.status, MESSAGES[outcome.status] || MESSAGES.failed);
        });
    }
  }

  if (typeof customElements !== "undefined" && !customElements.get("papyrus-signup")) {
    customElements.define("papyrus-signup", PapyrusSignup);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { sign: sign, submit: submit };
})();
