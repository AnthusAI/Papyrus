/* papyrus-video-v1.js: the click-to-play video player of a Papyrus site.
 *
 * The page holds a poster (our own copy of the thumbnail), a plain link to the video, and a button. Nothing on the page contacts the video
 * provider. This script reveals the button; on a click, Enter or Space it swaps the poster for the provider's player. It
 * only ever creates a frame for an address that starts with the player address of a provider it knows, and it creates it once per player.
 */
(function () {
  "use strict";
  // The only frame addresses this script will create: the player address of each provider in markus_renderer/video.py REGISTRY (a test compares the two lists).
  // A site's Content-Security-Policy fragment (_config/content-security-policy.txt) narrows these further to the providers the site lists.
  var EMBED_PREFIXES = [
    "https://www.youtube-nocookie.com/embed/",
    "https://player.vimeo.com/video/",
    "https://www.instagram.com/p/"
  ];

  function allowed(address) {
    for (var index = 0; index < EMBED_PREFIXES.length; index += 1) {
      if (address.indexOf(EMBED_PREFIXES[index]) === 0) return true;
    }
    return false;
  }

  function play(player) {
    if (player.getAttribute("data-playing") === "true") return;
    var address = player.getAttribute("data-embed") || "";
    if (!allowed(address)) return;
    player.setAttribute("data-playing", "true");
    var frame = document.createElement("iframe");
    frame.setAttribute("src", address);
    frame.setAttribute("title", player.getAttribute("data-title") || "Video");
    frame.setAttribute("allow", "autoplay; encrypted-media; picture-in-picture");
    frame.setAttribute("allowfullscreen", "");
    frame.setAttribute("loading", "lazy");
    frame.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    while (player.firstChild) player.removeChild(player.firstChild);
    player.appendChild(frame);
    if (player.classList) player.classList.add("is-playing");
    if (frame.focus) frame.focus();
  }

  function setup(player) {
    if (player.getAttribute("data-ready") === "true") return;
    var button = player.querySelector("button");
    if (!button) return;
    player.setAttribute("data-ready", "true");
    if (player.classList) player.classList.add("is-ready");
    // The poster link stays as the picture behind the button; the button is the one control, so the link leaves the tab order and the reader tree.
    var link = player.querySelector("a");
    if (link) {
      link.setAttribute("tabindex", "-1");
      link.setAttribute("aria-hidden", "true");
    }
    button.addEventListener("click", function () { play(player); });
    button.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
        if (event.preventDefault) event.preventDefault();
        play(player);
      }
    });
  }

  function run() {
    var players = document.querySelectorAll("[data-papyrus-video]");
    for (var index = 0; index < players.length; index += 1) setup(players[index]);
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
    else run();
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { play: play, setup: setup, run: run };
})();
