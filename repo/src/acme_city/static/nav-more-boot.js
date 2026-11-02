/* More tools in the side navigation.

   On a desktop the group starts open. On a phone it starts shut, and the
   bottom bar keeps its own More, which is never opened here. The person's
   choice is kept in sessionStorage for the session. If storage is missing
   the default still applies.

   The script runs in the head, before the body is painted. It only marks
   the root when the group should be shut. The markup itself is open, so a
   desktop does not flash shut, and the mark hides the list on a phone or
   after a choice of closed, so that does not flash open either. The page
   script then sets the open attribute to match. */

(function () {
  "use strict";

  var choice = null;
  try {
    choice = window.sessionStorage.getItem("acme-nav-more");
  } catch (error) {
    choice = null;
  }
  var phone = false;
  try {
    /* The same width at which the side navigation gives way to the bottom
       bar (app.css, max-width: 860px). */
    phone = window.matchMedia("(max-width: 860px)").matches;
  } catch (error) {
    phone = false;
  }
  if (phone || choice === "closed") {
    document.documentElement.setAttribute("data-nav-more", "shut");
  }
})();
