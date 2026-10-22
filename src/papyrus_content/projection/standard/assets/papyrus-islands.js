/* Papyrus islands runtime. The site bundle assigns window.papyrusIslands = { Name: (element, props) => ... }
   (merge into any existing object, do not replace it). Each [data-island] mount point calls its function once. */
document.addEventListener("DOMContentLoaded", function () {
  var registry = window.papyrusIslands || {};
  document.querySelectorAll("[data-island]").forEach(function (element) {
    var name = element.getAttribute("data-island");
    var mount = registry[name];
    if (typeof mount !== "function") {
      console.warn("Papyrus island not registered: " + name);
      return;
    }
    var props = {};
    try {
      props = JSON.parse(element.getAttribute("data-props") || "{}");
    } catch (error) {
      console.warn("Papyrus island " + name + " has unreadable props", error);
    }
    try {
      mount(element, props);
      // The text fallback (summary="...") is for readers without JavaScript; the mounted island replaces it.
      var fallback = element.querySelector(":scope > .papyrus-island-summary");
      if (fallback) fallback.remove();
    } catch (error) {
      console.warn("Papyrus island " + name + " failed", error);
    }
  });
});
