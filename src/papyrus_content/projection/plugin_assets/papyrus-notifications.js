/*
 * <papyrus-notifications>: the subscribe form of a Papyrus site that enables the notifications plugin.
 *
 * Framework-free and dependency-free; it sets no inline script or style attribute, so it works under a strict CSP.
 * Include it once with
 *   <script src="/_plugins/papyrus-notifications@1.js" defer></script>
 * and place the element anywhere in a page (the projected /notifications/ page does):
 *   <papyrus-notifications></papyrus-notifications>
 *
 * Attributes (all optional)
 *   lists       comma separated list ids to offer                                             default: every list the site offers
 *   consent     the consent sentence shown under the form and recorded with the signup        default: a plain sentence
 *   endpoint    where to post                                                                 default "/api/notifications/subscribe"
 *   state       where to read the offered lists (GET, kind=offered)                           default "/api/notifications/state"
 *   form-id     recorded with the consent evidence                                            default "notifications"
 *   label       accessible name of the email input                                            default "Email address"
 *   button      button text                                                                   default "Subscribe"
 *   success     message after a request was accepted                                          default "Check your email to confirm your subscription."
 *
 * One list: no choice to make, the consent sentence and the button are the opt-in. Several lists: one button per list, each Off until
 * pressed (nothing is pre-chosen), and at least one must be On. On and Off are words as well as a Lucide bell or bell-off. The request
 * carries a hidden field that people never fill (`website`) and the time the form rendered; the server drops requests from bots without
 * saying so. Whatever the server knows about the address, the answer is the same, so the message never says whether it was already subscribed.
 *
 * Styling hooks (the element renders into its own light DOM): form.markus-notifications-form, label.markus-notifications-label,
 * input.markus-notifications-input, button.markus-notifications-toggle[aria-pressed], button.markus-button, p.markus-notifications-consent,
 * p.markus-notifications-status[data-state]. Every status is words plus a mark, never colour alone. A "papyrus-notifications" event with
 * detail.status fires on the element after each attempt. Without JavaScript the element is empty.
 */
(function () {
  "use strict";

  var DEFAULT_ENDPOINT = "/api/notifications/subscribe";
  var DEFAULT_STATE = "/api/notifications/state";
  var DEFAULT_CONSENT = "I agree to receive these emails and understand that I can unsubscribe at any time.";
  var MESSAGES = {
    invalid_email: "Please enter a valid email address.",
    invalid_lists: "Choose at least one thing to get.",
    no_lists: "Choose at least one thing to get.",
    unavailable: "Notifications are not available right now. Please try again later.",
    failed: "Something went wrong. Please try again later.",
    unconfigured: "This form is not set up."
  };
  var SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" data-icon="';
  var ICONS = {
    mail: SVG + 'mail"><path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>',
    bell: SVG + 'bell"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/></svg>',
    "bell-off": SVG + 'bell-off"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/></svg>',
    "circle-check": SVG + 'circle-check"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
    "triangle-alert": SVG + 'triangle-alert"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
  };

  function submit(endpoint, payload) {
    return fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (response.status === 202 && body.status === "check_email") return { status: "check_email" };
        if (response.status === 400 && MESSAGES[body.status]) return { status: body.status };
        if (response.status === 503 || response.status === 502) return { status: "unavailable" };
        return { status: "failed" };
      });
    });
  }

  function offered(stateUrl) {
    return fetch(stateUrl + "?kind=offered", { credentials: "same-origin", cache: "no-store", headers: { accept: "application/json" } }).then(function (response) {
      return response.json().then(function (body) { return response.ok && Array.isArray(body.lists) ? body.lists : []; });
    }).catch(function () { return []; });
  }

  function element(tag, className, attributes) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    Object.keys(attributes || {}).forEach(function (name) { node.setAttribute(name, attributes[name]); });
    return node;
  }

  function mark(name) {
    var holder = element("span", "markus-notifications-mark");
    holder.innerHTML = ICONS[name];
    return holder;
  }

  var counter = 0;
  var Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

  class PapyrusNotifications extends Base {
    connectedCallback() {
      if (this.firstChild) return;
      counter += 1;
      this.endpoint = this.getAttribute("endpoint") || DEFAULT_ENDPOINT;
      this.consent = this.getAttribute("consent") || DEFAULT_CONSENT;
      this.formId = this.getAttribute("form-id") || "notifications";
      this.renderedAt = Date.now();
      this.base = "papyrus-notifications-" + counter;
      this.lists = [];
      this.boxes = [];

      var form = element("form", "markus-notifications-form", { novalidate: "" });
      var label = element("label", "markus-notifications-label", { for: this.base + "-email" });
      label.textContent = this.getAttribute("label") || "Email address";
      this.input = element("input", "markus-notifications-input", {
        id: this.base + "-email", type: "email", name: "email", required: "", maxlength: "254", autocomplete: "email"
      });
      form.appendChild(label);
      form.appendChild(this.input);
      this.choices = element("div", "markus-notifications-lists");
      form.appendChild(this.choices);

      /* A field people never see or reach. CSSOM assignments are allowed under a strict CSP; a style attribute is not. */
      var trap = element("div", "markus-notifications-trap", { "aria-hidden": "true" });
      trap.style.position = "absolute";
      trap.style.left = "-10000px";
      trap.style.width = "1px";
      trap.style.height = "1px";
      trap.style.overflow = "hidden";
      this.trap = element("input", "", { type: "text", name: "website", tabindex: "-1", autocomplete: "off" });
      trap.appendChild(this.trap);
      form.appendChild(trap);

      this.button = element("button", "markus-button markus-notifications-button", { type: "submit" });
      this.button.appendChild(mark("mail"));
      var text = element("span");
      text.textContent = this.getAttribute("button") || "Subscribe";
      this.button.appendChild(text);
      form.appendChild(this.button);
      var consent = element("p", "markus-notifications-consent");
      consent.textContent = this.consent;
      form.appendChild(consent);
      this.status = element("p", "markus-notifications-status", { role: "status", "aria-live": "polite" });
      form.appendChild(this.status);
      form.addEventListener("submit", this.onSubmit.bind(this));
      this.appendChild(form);

      var wanted = (this.getAttribute("lists") || "").split(",").map(function (id) { return id.trim(); }).filter(Boolean);
      var self = this;
      this.ready = offered(this.getAttribute("state") || DEFAULT_STATE).then(function (known) {
        self.lists = known.filter(function (entry) { return entry && entry.id && (wanted.length === 0 || wanted.indexOf(entry.id) >= 0); });
        if (self.lists.length > 1) self.lists.forEach(function (entry, index) { self.addChoice(entry, index); });
      });
    }

    addChoice(entry, index) {
      var row = element("div", "markus-notifications-list");
      var button = element("button", "markus-notifications-toggle", { type: "button", id: this.base + "-list-" + index, "data-list": entry.id });
      var icon = element("span", "markus-notifications-mark");
      var name = element("span", "markus-notifications-name");
      name.textContent = entry.name || entry.id;
      var word = element("span", "markus-notifications-state");
      function paint(on) {
        button.setAttribute("aria-pressed", on ? "true" : "false");
        icon.innerHTML = ICONS[on ? "bell" : "bell-off"];
        word.textContent = on ? "On" : "Off";
      }
      button.addEventListener("click", function () { paint(button.getAttribute("aria-pressed") !== "true"); });
      paint(false);
      button.appendChild(icon);
      button.appendChild(name);
      button.appendChild(word);
      row.appendChild(button);
      if (entry.description) {
        var description = element("p");
        description.textContent = entry.description;
        row.appendChild(description);
      }
      this.choices.appendChild(row);
      this.boxes.push(button);
    }

    show(state, text) {
      this.status.setAttribute("data-state", state);
      this.status.innerHTML = ICONS[state === "check_email" ? "circle-check" : "triangle-alert"];
      var words = element("span");
      words.textContent = text;
      this.status.appendChild(words);
      this.dispatchEvent(new CustomEvent("papyrus-notifications", { detail: { status: state } }));
    }

    chosenLists() {
      if (this.lists.length === 1) return [this.lists[0].id];
      return this.boxes.filter(function (box) { return box.getAttribute("aria-pressed") === "true"; }).map(function (box) { return box.getAttribute("data-list"); });
    }

    onSubmit(event) {
      event.preventDefault();
      var self = this;
      return this.ready.then(function () {
        if (self.lists.length === 0) return self.show("unconfigured", MESSAGES.unconfigured);
        var value = self.input.value.trim();
        if (!value || !self.input.checkValidity()) return self.show("invalid_email", MESSAGES.invalid_email);
        var chosen = self.chosenLists();
        if (chosen.length === 0) return self.show("no_lists", MESSAGES.no_lists);
        self.button.disabled = true;
        self.status.removeAttribute("data-state");
        self.status.textContent = "Sending...";
        return submit(self.endpoint, {
          email: value,
          lists: chosen,
          page: window.location.origin + window.location.pathname,
          consent: self.consent,
          formId: self.formId,
          website: self.trap.value,
          renderedAt: self.renderedAt
        })
          .catch(function () { return { status: "failed" }; })
          .then(function (outcome) {
            self.button.disabled = false;
            if (outcome.status === "check_email") {
              self.input.value = "";
              return self.show("check_email", self.getAttribute("success") || "Check your email to confirm your subscription.");
            }
            self.show(outcome.status, MESSAGES[outcome.status] || MESSAGES.failed);
          });
      });
    }
  }

  if (typeof customElements !== "undefined" && !customElements.get("papyrus-notifications")) {
    customElements.define("papyrus-notifications", PapyrusNotifications);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { submit: submit, offered: offered };
})();
