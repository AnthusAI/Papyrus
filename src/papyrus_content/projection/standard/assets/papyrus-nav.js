(function () {
  var toggle = document.querySelector(".markus-nav-toggle");
  var nav = document.getElementById("site-nav");
  if (!toggle || !nav) return;
  document.documentElement.classList.add("markus-nav-js");
  function set(open) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    nav.classList.toggle("is-open", open);
  }
  toggle.addEventListener("click", function () { set(toggle.getAttribute("aria-expanded") !== "true"); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") { set(false); toggle.focus(); }
  });
})();
