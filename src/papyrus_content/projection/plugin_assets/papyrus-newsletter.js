/*
 * <papyrus-newsletter>: a double opt-in newsletter signup form for a Papyrus site that enables the newsletter plugin.
 *
 * Framework-free and dependency-free; it sets no inline script or style attribute, so it works under a strict CSP.
 * Include it once with
 *   <script src="/_plugins/papyrus-newsletter@1.js" defer></script>
 * and place the element anywhere in a page:
 *   <papyrus-newsletter lists="weekly,alerts-x"
 *     consent="I agree to get the weekly email and breaking alerts, and can unsubscribe at any time."></papyrus-newsletter>
 *
 * Attributes
 *   lists       comma separated list ids to offer; each must be a list of the site's newsletter plugin   required*
 *   data-lists  JSON array of {id, name, description}: custom.papyrusPlugins.newsletter.lists from       optional
 *               amplify_outputs.json. Labels the checkboxes; without it the list id is the label.
 *   consent     the consent sentence shown under the form and recorded with the signup                   default: a plain sentence
 *   endpoint    where to post                                                                            default "/api/newsletter/subscribe"
 *   form-id     recorded with the consent evidence                                                       default "newsletter"
 *   label       accessible name of the email input                                                       default "Email address"
 *   button      button text                                                                              default "Subscribe"
 *   success     message after a request was accepted                                                     default "Check your inbox to confirm your subscription."
 *   (*) or set once for the whole site: window.papyrusNewsletter = { lists: [{ id, name, description }], endpoint }
 *
 * One list: no checkbox, the consent sentence and the button are the opt-in. Several lists: one unticked checkbox per list
 * (nothing is pre-ticked) and at least one must be chosen. The request carries a hidden field that people never fill
 * (`website`) and the time the form rendered; the server drops requests from bots without saying so. Whatever the server knows about
 * the address, the answer is the same, so the message never says whether the address was already subscribed.
 *
 * Styling hooks (the element renders into its own light DOM): form.papyrus-newsletter, label.papyrus-newsletter-label,
 * input.papyrus-newsletter-input, fieldset.papyrus-newsletter-lists, button.papyrus-newsletter-button,
 * p.papyrus-newsletter-consent, p.papyrus-newsletter-status[data-state]. Every status is words, never colour alone. A
 * "papyrus-newsletter" event with detail.status fires on the element after each attempt. Without JavaScript the element is empty.
 */
(function () {
  "use strict";

  var DEFAULT_ENDPOINT = "/api/newsletter/subscribe";
  var DEFAULT_CONSENT = "I agree to receive these emails and understand that I can unsubscribe at any time.";
  var MESSAGES = {
    invalid_email: "Error: please enter a valid email address.",
    invalid_lists: "Error: choose at least one list.",
    no_lists: "Error: choose at least one list.",
    failed: "Error: something went wrong. Please try again later.",
    unconfigured: "Error: this form is not set up."
  };

  function submit(settings, payload) {
    return fetch(settings.endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (response.status === 202 && body.status === "check_email") return { status: "check_email" };
        if (response.status === 400 && MESSAGES[body.status]) return { status: body.status };
        return { status: "failed" };
      });
    });
  }

  function element(tag, className, attributes) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    Object.keys(attributes || {}).forEach(function (name) { node.setAttribute(name, attributes[name]); });
    return node;
  }

  function parseJson(text) {
    try { return JSON.parse(text); } catch (error) { return null; }
  }

  var counter = 0;
  var Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

  class PapyrusNewsletter extends Base {
    connectedCallback() {
      if (this.firstChild) return;
      counter += 1;
      var site = window.papyrusNewsletter || {};
      var known = parseJson(this.getAttribute("data-lists") || "") || site.lists || [];
      var ids = (this.getAttribute("lists") || "").split(",").map(function (id) { return id.trim(); }).filter(Boolean);
      if (ids.length === 0) ids = known.map(function (entry) { return entry.id; });
      this.lists = ids.map(function (id) {
        var match = known.filter(function (entry) { return entry && entry.id === id; })[0] || {};
        return { id: id, name: match.name || id, description: match.description || "" };
      });
      this.settings = { endpoint: this.getAttribute("endpoint") || site.endpoint || DEFAULT_ENDPOINT };
      this.consent = this.getAttribute("consent") || DEFAULT_CONSENT;
      this.formId = this.getAttribute("form-id") || "newsletter";
      this.renderedAt = Date.now();
      var base = "papyrus-newsletter-" + counter;

      var form = element("form", "papyrus-newsletter", { novalidate: "" });
      var label = element("label", "papyrus-newsletter-label", { for: base + "-email" });
      label.textContent = this.getAttribute("label") || "Email address";
      this.input = element("input", "papyrus-newsletter-input", {
        id: base + "-email", type: "email", name: "email", required: "", maxlength: "254", autocomplete: "email"
      });
      form.appendChild(label);
      form.appendChild(this.input);

      this.boxes = [];
      if (this.lists.length > 1) {
        var fieldset = element("fieldset", "papyrus-newsletter-lists");
        var legend = element("legend", "papyrus-newsletter-legend");
        legend.textContent = "Choose your lists";
        fieldset.appendChild(legend);
        this.lists.forEach(function (entry, index) {
          var row = element("div", "papyrus-newsletter-list");
          var box = element("input", "papyrus-newsletter-checkbox", { type: "checkbox", id: base + "-list-" + index, value: entry.id });
          var text = element("label", "papyrus-newsletter-list-label", { for: base + "-list-" + index });
          text.textContent = entry.name + (entry.description ? ": " + entry.description : "");
          row.appendChild(box);
          row.appendChild(text);
          fieldset.appendChild(row);
          this.boxes.push(box);
        }, this);
        form.appendChild(fieldset);
      }

      /* A field people never see or reach. CSSOM assignments are allowed under a strict CSP; a style attribute is not. */
      var trap = element("div", "papyrus-newsletter-trap", { "aria-hidden": "true" });
      trap.style.position = "absolute";
      trap.style.left = "-10000px";
      trap.style.width = "1px";
      trap.style.height = "1px";
      trap.style.overflow = "hidden";
      this.trap = element("input", "", { type: "text", name: "website", tabindex: "-1", autocomplete: "off" });
      trap.appendChild(this.trap);
      form.appendChild(trap);

      this.button = element("button", "papyrus-newsletter-button", { type: "submit" });
      this.button.textContent = this.getAttribute("button") || "Subscribe";
      form.appendChild(this.button);
      var consent = element("p", "papyrus-newsletter-consent");
      consent.textContent = this.consent;
      form.appendChild(consent);
      this.status = element("p", "papyrus-newsletter-status", { role: "status", "aria-live": "polite" });
      form.appendChild(this.status);
      form.addEventListener("submit", this.onSubmit.bind(this));
      this.appendChild(form);
    }

    show(state, text) {
      this.status.setAttribute("data-state", state);
      this.status.textContent = text;
      this.dispatchEvent(new CustomEvent("papyrus-newsletter", { detail: { status: state } }));
    }

    chosenLists() {
      if (this.lists.length === 1) return [this.lists[0].id];
      return this.boxes.filter(function (box) { return box.checked; }).map(function (box) { return box.value; });
    }

    onSubmit(event) {
      event.preventDefault();
      if (this.lists.length === 0) return this.show("unconfigured", MESSAGES.unconfigured);
      var value = this.input.value.trim();
      if (!value || !this.input.checkValidity()) return this.show("invalid_email", MESSAGES.invalid_email);
      var chosen = this.chosenLists();
      if (chosen.length === 0) return this.show("no_lists", MESSAGES.no_lists);
      this.button.disabled = true;
      this.status.removeAttribute("data-state");
      this.status.textContent = "Sending...";
      var self = this;
      submit(this.settings, {
        email: value,
        lists: chosen,
        page: window.location.origin + window.location.pathname,
        consent: this.consent,
        formId: this.formId,
        website: this.trap.value,
        renderedAt: this.renderedAt
      })
        .catch(function () { return { status: "failed" }; })
        .then(function (outcome) {
          self.button.disabled = false;
          if (outcome.status === "check_email") {
            self.input.value = "";
            return self.show("check_email", self.getAttribute("success") || "Check your inbox to confirm your subscription.");
          }
          self.show(outcome.status, MESSAGES[outcome.status] || MESSAGES.failed);
        });
    }
  }

  if (typeof customElements !== "undefined" && !customElements.get("papyrus-newsletter")) {
    customElements.define("papyrus-newsletter", PapyrusNewsletter);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { submit: submit };
})();
