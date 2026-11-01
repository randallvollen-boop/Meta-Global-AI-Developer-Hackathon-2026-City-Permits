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
   - the step graph of an agent run is replayed after the run; the script of
     the page (static/agent-progress.js) moves the cards of the graph and
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

    var details = document.createElement("details");
    details.className = "feedback-more";
    details.setAttribute("data-testid", "feedback-more");
    var summary = document.createElement("summary");
    summary.textContent = "More details";
    details.appendChild(summary);

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
    details.appendChild(list);
    region.appendChild(details);
    if (outcome.message) toast(outcome.message);
  }

  /* ------------------------------------------- the page after a changed record */
  function keepOpenDetails(oldRoot, newRoot) {
    /* The action panels a person had open stay open after the page is read
       again, so the flow of the screen is not interrupted. */
    var open = [];
    oldRoot.querySelectorAll("details").forEach(function (node, index) {
      if (node.open) open.push(index);
    });
    var all = newRoot.querySelectorAll("details");
    open.forEach(function (index) {
      if (all[index]) all[index].open = true;
    });
  }

  function formValues(root) {
    /* The values of the action forms of the screen: what a person has typed
       and the version the server rendered the form with.  The forms are
       listed per action, in the order they stand on the screen. */
    var forms = [];
    root.querySelectorAll("form").forEach(function (form) {
      var marker = form.querySelector('[name="action_id"]');
      var typed = {};
      var version = {};
      form.querySelectorAll("input, select, textarea").forEach(function (control) {
        if (!control.name) return;
        var value =
          control.type === "checkbox" || control.type === "radio"
            ? { checked: control.checked }
            : { value: control.value };
        if (control.type === "hidden") {
          if (control.name.indexOf("expected_") === 0) version[control.name] = value;
        } else {
          typed[control.name] = value;
        }
      });
      forms.push({
        action: marker ? marker.value : "",
        typed: typed,
        version: version
      });
    });
    return forms;
  }

  function groupByAction(forms) {
    /* The forms of the screen, grouped by the action they send. */
    var groups = {};
    forms.forEach(function (entry) {
      if (!groups[entry.action]) groups[entry.action] = [];
      groups[entry.action].push(entry);
    });
    return groups;
  }

  function keepValues(newRoot, forms, sent) {
    /* What a person has typed is put back into the fresh form of the same
       action, so reading the page again does not lose it.  The action that
       was just sent keeps the version it was made against, so sending it
       again is the same command. */
    var fresh = groupByAction(
      Array.prototype.map.call(newRoot.querySelectorAll("form"), function (form) {
        var marker = form.querySelector('[name="action_id"]');
        return { action: marker ? marker.value : "", form: form };
      })
    );
    var old = groupByAction(forms);
    Object.keys(old).forEach(function (action) {
      old[action].forEach(function (entry, index) {
        var candidate = fresh[action] ? fresh[action][index] : null;
        if (!candidate) return;
        var values = entry.typed;
        if (action === sent) {
          values = Object.assign({}, entry.typed, entry.version);
        }
        Object.keys(values).forEach(function (name) {
          var control = candidate.form.querySelector('[name="' + name + '"]');
          if (!control) return;
          if ("checked" in values[name]) {
            control.checked = values[name].checked;
          } else {
            control.value = values[name].value;
          }
        });
      });
    });
  }

  function activeTab() {
    /* The tab of the screen the person is looking at. */
    var selected = document.querySelector(
      '[data-testid="workspace-tabs"] [aria-selected="true"]'
    );
    return selected ? selected.getAttribute("data-tab") : "";
  }

  function swapThePage(next, sent) {
    /* The live parts of the page are replaced by the ones the server just
       rendered: the content of the screen and the navigation with its
       counts.  The banner, the feedback region and the theme stay. */
    var tab = activeTab();
    var main = document.getElementById("main");
    var freshMain = next.getElementById("main");
    if (main && freshMain) {
      keepOpenDetails(main, freshMain);
      keepValues(freshMain, formValues(main), sent);
      main.replaceWith(freshMain);
    }
    var side = document.querySelector(".shell > aside");
    var freshSide = next.querySelector(".shell > aside");
    if (side && freshSide) side.replaceWith(freshSide);
    initUi();
    if (tab) {
      /* The person keeps the tab of the screen they were working in. */
      var button = document.querySelector(
        '[data-testid="workspace-tabs"] [data-tab="' + tab + '"]'
      );
      if (button && button.getAttribute("aria-selected") !== "true") button.click();
    }
    announceRun(sent);
  }

  function announceRun(sent) {
    /* The step graph of an agent run is replayed after the run, so the
       operator sees the order the agent worked in.  The replay shows the
       states the run recorded and never claims to be a live run. */
    if (typeof sent !== "string") return;
    if (sent.indexOf("agent.run.") !== 0 && sent !== "agent.retry") return;
    document.dispatchEvent(
      new CustomEvent("acme:agent-run", { detail: { action: sent } })
    );
  }

  function rereadThePage(sent) {
    /* Read the page again and put the fresh parts in place.  The page is
       never left, so the person keeps their place in the flow. */
    return fetch(window.location.href, { credentials: "same-origin" })
      .then(function (response) {
        return response.ok ? response.text() : "";
      })
      .then(function (html) {
        if (!html) return;
        swapThePage(new DOMParser().parseFromString(html, "text/html"), sent);
      })
      .catch(function () {
        /* The page stays as it is; the action itself is already recorded. */
      });
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
        // An accepted action changed a record, so the page is read from the
        // server again.  The panels then show the state in the database and
        // not the state of the page that was loaded before the action, so a
        // person never has to reload to see what the action did.  A refused
        // action changed nothing, so the page stays as it is.
        if (result.payload.status === "accepted") {
          var marker = form.querySelector('[name="action_id"]');
          rereadThePage(marker ? marker.value : "");
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
    var initial = tabs.filter(function (item) {
      return item.getAttribute("aria-selected") === "true";
    })[0];
    if (tabs.length) select(initial || tabs[0], false);
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

  function initUi() {
    /* The parts of the interface that live inside the content of the screen.
       They are bound again when the page is read again after an action. */
    initTabs();
    initReplay();
    initQueueRows();
    initIconPicker();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var region = document.querySelector(".feedback");
    if (region && !region.id) {
      region.id = REGION_ID;
    }
    initTheme();
    initUi();
  });
  // The script is deferred, so DOMContentLoaded may already have fired in
  // some embedding contexts; initTheme is idempotent, run it now as well.
  if (document.readyState !== "loading") {
    initTheme();
  }
})();
