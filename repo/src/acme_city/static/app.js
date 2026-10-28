/* The local script of the ACME City demonstration interface.

   The script is an enhancement, not a requirement: every action works
   without it.  When it is present an action form is submitted in the
   background and the typed outcome of the action is rendered in the
   feedback region, so the user learns what changed, where it was written
   and whether a source or a consumer still has to acknowledge it.

   Progressive enhancements (no server round-trip for chrome):
   - theme toggle persisted in localStorage (system setting otherwise);
   - persona segmented control submits its server form on click;
   - tabs on the permit workspace (all panels stacked without JS);
   - Replay run animates the recorded 5-node strip client-side only and
     never sends a request;
   - work-queue rows navigate to their case;
   - toast mirrors the feedback outcome. */

(function () {
  "use strict";

  var REGION_ID = "ui-feedback-region";

  function reducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  /* -------------------------------------------------------------- theme */
  function syncThemeIcon() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    var root = document.documentElement;
    var dark = root.getAttribute("data-theme")
      ? root.getAttribute("data-theme") === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    button.innerHTML =
      '<svg aria-hidden="true"><use href="#i-' + (dark ? "sun" : "moon") + '"/></svg>';
  }
  var themeBound = false;
  function initTheme() {
    // The script is deferred, so it can run initTheme twice (once at load, once on
    // DOMContentLoaded). A second click listener would undo every toggle.
    if (themeBound) return;
    themeBound = true;
    try {
      var stored = window.localStorage.getItem("acme-theme");
      if (stored === "dark" || stored === "light") {
        document.documentElement.setAttribute("data-theme", stored);
      }
    } catch (error) {
      /* Storage may be unavailable; the system setting then applies. */
    }
    syncThemeIcon();
    var button = document.getElementById("theme-toggle");
    if (button) {
      button.addEventListener("click", function () {
        var root = document.documentElement;
        var dark = root.getAttribute("data-theme")
          ? root.getAttribute("data-theme") === "dark"
          : window.matchMedia("(prefers-color-scheme: dark)").matches;
        var next = dark ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try {
          window.localStorage.setItem("acme-theme", next);
        } catch (error) {
          /* The choice then lasts for this page only. */
        }
        syncThemeIcon();
      });
    }
  }

  /* -------------------------------------------------------------- toast */
  function toast(message) {
    var node = document.getElementById("toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("on");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () {
      node.classList.remove("on");
    }, 2400);
  }

  /* ----------------------------------------------------------- feedback */
  function feedbackRegion() {
    var region = document.getElementById(REGION_ID);
    if (region) {
      return region;
    }
    region = document.createElement("section");
    region.id = REGION_ID;
    region.className = "feedback";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    region.setAttribute("data-testid", "feedback");
    var main = document.getElementById("main");
    if (main && main.parentNode) {
      main.parentNode.insertBefore(region, main);
    } else {
      document.body.insertBefore(region, document.body.firstChild);
    }
    return region;
  }

  function renderOutcome(region, outcome) {
    var accepted = outcome.status === "accepted";
    region.className = "feedback " + (accepted ? "feedback-accepted" : "feedback-denied");
    region.setAttribute("data-outcome", outcome.status || "denied");
    region.innerHTML = "";

    var title = document.createElement("h2");
    title.className = "feedback-title";
    title.textContent = accepted ? "Last action" : "The action was refused";
    region.appendChild(title);

    var message = document.createElement("p");
    message.className = "feedback-message";
    message.setAttribute("data-testid", "feedback-message");
    message.textContent = outcome.message || "";
    region.appendChild(message);

    var list = document.createElement("dl");
    list.className = "feedback-detail";
    var rows = [
      ["Destination", outcome.destination || "not applicable", "feedback-destination"],
      ["State", outcome.state || "not applicable", "feedback-state"],
      [
        "Pending",
        outcome.pending
          ? "yes, the source or the consumer has not acknowledged yet"
          : "no",
        "feedback-pending"
      ],
      [
        "Version",
        outcome.version === null || outcome.version === undefined
          ? "not applicable"
          : String(outcome.version),
        "feedback-version"
      ],
      ["Affected", (outcome.affected || []).join(", ") || "none", "feedback-affected"]
    ];
    rows.forEach(function (row) {
      var wrapper = document.createElement("div");
      var term = document.createElement("dt");
      term.textContent = row[0];
      var definition = document.createElement("dd");
      definition.setAttribute("data-testid", row[2]);
      definition.textContent = row[1];
      wrapper.appendChild(term);
      wrapper.appendChild(definition);
      list.appendChild(wrapper);
    });
    region.appendChild(list);
    if (outcome.message) toast(outcome.message);
  }

  function submit(form) {
    var button = form.querySelector("button[type=submit]");
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    form.setAttribute("aria-busy", "true");
    fetch(form.action, {
      method: form.method || "post",
      body: new FormData(form),
      headers: {
        Accept: "application/json",
        "X-Requested-With": "acme-city-ui"
      },
      credentials: "same-origin",
      redirect: "follow"
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload };
        });
      })
      .then(function (result) {
        renderOutcome(feedbackRegion(), result.payload);
        if (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        }
        form.removeAttribute("aria-busy");
        // Icon save/generate changes what the page shows: reload so the
        // server-rendered icon, history and caps stay authoritative.
        if (form.closest("[data-icon-panel]")) {
          window.setTimeout(function () {
            window.location.reload();
          }, 350);
        }
      })
      .catch(function () {
        renderOutcome(feedbackRegion(), {
          status: "denied",
          message: "The action could not be sent. Use the screen again to retry."
        });
        if (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        }
        form.removeAttribute("aria-busy");
      });
  }

  /* --------------------------------------------------------------- tabs */
  function initTabs() {
    var tablist = document.querySelector('[data-testid="workspace-tabs"]');
    if (!tablist) return;
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));
    var panels = {};
    tabs.forEach(function (tab) {
      var panel = document.getElementById(tab.getAttribute("aria-controls") || "");
      if (panel) panels[tab.id] = panel;
    });
    function select(tab, focus) {
      tabs.forEach(function (item) {
        var selected = item === tab;
        item.setAttribute("aria-selected", selected ? "true" : "false");
        item.tabIndex = selected ? 0 : -1;
        var panel = panels[item.id];
        if (panel) panel.hidden = !selected;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () {
        select(tab, false);
      });
      tab.addEventListener("keydown", function (event) {
        var next = null;
        if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
        if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
        if (event.key === "Home") next = tabs[0];
        if (event.key === "End") next = tabs[tabs.length - 1];
        if (next) {
          event.preventDefault();
          select(next, true);
        }
      });
    });
    if (tabs.length) select(tabs[0], false);
  }

  /* -------------------------------------------------------- muse replay */
  function initReplay() {
    var button = document.querySelector("[data-replay-run]");
    if (!button) return;
    button.addEventListener("click", function () {
      var strip = document.querySelector("[data-testid='muse-run-strip']");
      if (!strip) return;
      var nodes = Array.prototype.slice.call(strip.querySelectorAll(".rnode"));
      if (!nodes.length || button.disabled) return;
      var original = nodes.map(function (node) {
        return node.className;
      });
      var reduce = reducedMotion();
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      var index = 0;
      function finish() {
        nodes.forEach(function (node, position) {
          node.className = original[position];
        });
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
      function tick() {
        nodes.forEach(function (node, position) {
          node.className = original[position]
            .replace(/\bpending\b/g, "")
            .replace(/\brunning\b/g, "");
          if (position < index) {
            if (node.className.indexOf("ok") === -1) node.className += " ok";
          } else if (position === index) {
            node.className += " running";
          } else {
            node.className += " pending";
          }
        });
        index += 1;
        if (index <= nodes.length) {
          window.setTimeout(tick, reduce ? 0 : 420);
        } else {
          finish();
        }
      }
      tick();
    });
  }

  /* --------------------------------------------------- queue row links */
  function initQueueRows() {
    document.querySelectorAll("tr.row[data-href]").forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, select, textarea, form, details")) return;
        window.location.href = row.getAttribute("data-href");
      });
    });
  }

  /* ------------------------------------------------------ icon picker */
  function initIconPicker() {
    document.querySelectorAll("[data-icon-history]").forEach(function (group) {
      var targetId = group.getAttribute("data-icon-history");
      var input = document.getElementById(targetId || "");
      if (!input) return;
      group.querySelectorAll("[data-icon-pick]").forEach(function (button) {
        button.addEventListener("click", function () {
          input.value = button.getAttribute("data-icon-pick") || "";
          group.querySelectorAll("[data-icon-pick]").forEach(function (other) {
            other.setAttribute(
              "aria-pressed",
              other === button ? "true" : "false"
            );
          });
        });
      });
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.classList || !form.classList.contains("action-form")) {
      return;
    }
    event.preventDefault();
    submit(form);
  });

  document.addEventListener("DOMContentLoaded", function () {
    var region = document.querySelector(".feedback");
    if (region && !region.id) {
      region.id = REGION_ID;
    }
    initTheme();
    initTabs();
    initReplay();
    initQueueRows();
    initIconPicker();
  });
  // The script is deferred, so DOMContentLoaded may already have fired in
  // some embedding contexts; initTheme is idempotent, run it now as well.
  if (document.readyState !== "loading") {
    initTheme();
  }
})();
