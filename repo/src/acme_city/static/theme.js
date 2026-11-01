/* The theme of the staff frame.

   Light is the default everywhere: the setting of the device is never
   followed, so a reader on a dark device sees the same light interface as
   everybody else.  The staff frame offers a dark mode, and the choice is
   kept in localStorage.

   The script runs in the head of the page, before the body is painted, so a
   page that was left in dark mode never flashes light first.  It only acts
   on a page that carries the dark mode control: the root element says so
   with data-theme-control.  Every other page (the City website, the landing
   of a signed-out reader, the downloaded documents) stays light. */

(function () {
  "use strict";

  var root = document.documentElement;
  if (!root.hasAttribute("data-theme-control")) return;

  var stored = null;
  try {
    stored = window.localStorage.getItem("acme-theme");
  } catch (error) {
    stored = null;
  }
  if (stored === "dark" || stored === "light") {
    root.setAttribute("data-theme", stored);
  }
})();
