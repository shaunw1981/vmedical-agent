/* Small progressive-enhancement script:
   1) register the service worker (PWA install + offline shell),
   2) close the mobile nav drawer after tapping a link.
   Core navigation works without this file (the drawer is a CSS checkbox). */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function (err) {
        console.warn("Service worker registration failed:", err);
      });
    });
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest(".sidebar a");
    if (link) {
      var toggle = document.getElementById("nav-toggle");
      if (toggle) toggle.checked = false;
    }
  });
})();
