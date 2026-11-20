(function () {
  var switchers = document.querySelectorAll("[data-language-switcher] details");
  if (!switchers.length) return;
  Array.prototype.forEach.call(switchers, function (details) {
    document.addEventListener("click", function (event) {
      if (details.open && !details.contains(event.target)) details.open = false;
    });
    details.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && details.open) { details.open = false; details.querySelector("summary").focus(); }
    });
    details.addEventListener("focusout", function (event) {
      if (details.open && event.relatedTarget && !details.contains(event.relatedTarget)) details.open = false;
    });
  });
})();
