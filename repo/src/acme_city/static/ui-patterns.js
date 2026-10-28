/* Shared interface patterns: information popover and detail drawer.

   An enhancement only.  Without this script the popover text is a <details>
   and a detail link is a plain link to the same page with ?detail=, which the
   server renders with the drawer open. */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("ui-js");

  var FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  /* ------------------------------------------------------ P1 info popover */
  var openInfo = null;

  function closeInfo(returnFocus) {
    if (!openInfo) return;
    var button = openInfo.button;
    button.setAttribute("aria-expanded", "false");
    openInfo.pop.hidden = true;
    openInfo.pop.classList.remove("ui-flip");
    openInfo = null;
    if (returnFocus) button.focus();
  }

  function showInfo(button) {
    var pop = document.getElementById(button.getAttribute("aria-controls"));
    if (!pop) return;
    closeInfo(false);
    pop.hidden = false;
    button.setAttribute("aria-expanded", "true");
    var box = pop.getBoundingClientRect();
    if (box.right > window.innerWidth - 8) pop.classList.add("ui-flip");
    openInfo = { button: button, pop: pop };
  }

  /* ------------------------------------------------------- P3 detail drawer */
  var drawer = null;
  var opener = null;

  function drawerEl() {
    drawer = drawer || document.getElementById("ui-drawer");
    return drawer;
  }
  function drawerOpen() {
    var el = drawerEl();
    return !!el && !el.hidden;
  }
  function focusables() {
    return Array.prototype.filter.call(drawerEl().querySelectorAll(FOCUSABLE), function (el) {
      return el.offsetParent !== null;
    });
  }
  function focusIntoDrawer() {
    var title = drawerEl().querySelector("#ui-drawer-title");
    if (title) title.focus();
    else {
      var items = focusables();
      if (items.length) items[0].focus();
    }
  }
  function urlWithDetail(value) {
    var url = new URL(window.location.href);
    url.searchParams.delete("detail");
    var search = url.searchParams.toString();
    if (value) {
      var parts = value.split(":");
      search += (search ? "&" : "") + "detail=" + encodeURIComponent(parts[0]) + ":" + encodeURIComponent(parts.slice(1).join(":"));
    }
    return url.pathname + (search ? "?" + search : "") + url.hash;
  }
  function setUrl(value) {
    try {
      window.history.replaceState(window.history.state, "", urlWithDetail(value));
    } catch (error) {
      /* The address is a convenience; the drawer still works. */
    }
  }

  function openDrawer(kind, id, trigger) {
    var el = drawerEl();
    if (!el) return false;
    closeInfo(false);
    if (trigger) opener = trigger;
    var from = urlWithDetail(null);
    var url = "/detail/" + encodeURIComponent(kind) + "/" + encodeURIComponent(id) + "?from=" + encodeURIComponent(from);
    return fetch(url, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then(function (response) {
        return response.text();
      })
      .then(function (html) {
        el.querySelector("#ui-drawer-content").innerHTML = html;
        el.hidden = false;
        el.classList.add("is-open");
        document.body.classList.add("ui-drawer-open");
        setUrl(kind + ":" + id);
        focusIntoDrawer();
      })
      .catch(function () {
        window.location.href = urlWithDetail(kind + ":" + id);
      });
  }

  function closeDrawer() {
    var el = drawerEl();
    if (!el || el.hidden) return;
    el.hidden = true;
    el.classList.remove("is-open");
    el.querySelector("#ui-drawer-content").innerHTML = "";
    document.body.classList.remove("ui-drawer-open");
    setUrl(null);
    var target = opener && document.contains(opener) ? opener : null;
    if (!target) target = document.getElementById("main");
    if (target) {
      if (!target.hasAttribute("tabindex") && target.tagName === "MAIN") target.setAttribute("tabindex", "-1");
      target.focus();
    }
    opener = null;
  }

  /* --------------------------------------------------------------- events */
  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;

    var infoButton = target.closest(".ui-info-btn");
    if (infoButton) {
      event.preventDefault();
      if (openInfo && openInfo.button === infoButton) closeInfo(false);
      else showInfo(infoButton);
      return;
    }
    if (openInfo && !target.closest(".ui-info-pop")) closeInfo(false);

    var closer = target.closest("[data-ui-drawer-close]");
    if (closer) {
      event.preventDefault();
      closeDrawer();
      return;
    }
    var link = target.closest("a[data-ui-detail]");
    if (link && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {
      event.preventDefault();
      openDrawer(link.getAttribute("data-detail-kind"), link.getAttribute("data-detail-id"), link);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      if (openInfo) {
        event.preventDefault();
        closeInfo(true);
        return;
      }
      if (drawerOpen()) {
        event.preventDefault();
        closeDrawer();
      }
      return;
    }
    if (event.key === "Tab" && drawerOpen()) {
      var items = focusables();
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      var active = document.activeElement;
      var inside = drawerEl().contains(active);
      if (!inside) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (active === first || active.id === "ui-drawer-title")) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  /* A drawer the server rendered open (?detail=) gets the same focus rules. */
  if (drawerOpen()) focusIntoDrawer();
})();
