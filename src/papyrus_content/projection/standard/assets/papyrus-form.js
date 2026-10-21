(function () {
  document.querySelectorAll("form[data-papyrus-form]").forEach(function (form) {
    var status = form.querySelector(".markus-form-status");
    function say(text, failed) {
      status.textContent = text;
      status.hidden = false;
      status.classList.toggle("is-error", failed);
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var body = {};
      new FormData(form).forEach(function (value, key) { body[key] = String(value); });
      body.page = location.pathname;
      var button = form.querySelector("button[type=submit]");
      button.disabled = true;
      fetch(form.dataset.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (response) {
        if (response.ok) { form.reset(); say(form.dataset.success, false); }
        else { say(form.dataset.failure, true); }
      }).catch(function () { say(form.dataset.failure, true); }).then(function () { button.disabled = false; });
    });
  });
})();
