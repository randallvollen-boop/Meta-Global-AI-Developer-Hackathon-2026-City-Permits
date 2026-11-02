/* The local script of the ACME City demonstration interface.

   The script is an enhancement, not a requirement: every action works
   without it.  When it is present an action form is submitted in the
   background and the typed outcome of the action is rendered in the panel of
   the last action, so the user learns what changed, where it was written
   and whether a source or a consumer still has to acknowledge it.

   Progressive enhancements (no server round-trip for chrome):
   - dark mode of the staff frame, persisted in localStorage;
   - tabs on the permit workspace (all panels stacked without JS);
   - Replay run animates the recorded 5-node strip client-side only and
     never sends a request;
   - the step graph of an agent run is replayed after the run; the script of
     the page (static/agent-progress.js) moves the cards of the graph and
     never sends a request;
   - work-queue rows navigate to their case;
   - the bell of the last action opens its panel, and the toast mirrors the
     outcome of the action. */

(function () {
  "use strict";

  var REGION_ID = "ui-feedback-region";
  var PANEL_ID = "ui-feedback-panel";
  var TOGGLE_ID = "last-action-toggle";

  function reducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  /* -------------------------------------------------------------- theme */
  /* The dark mode is a choice of the reader, kept in localStorage.  The
     choice is applied before the page is painted by static/theme.js, so this
     script only reads it and reports it on the control in the persona menu. */
  function themeIsDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }
  function syncThemeControl() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    var dark = themeIsDark();
    button.setAttribute("aria-pressed", dark ? "true" : "false");
    var state = button.querySelector('[data-testid="theme-state"]');
    if (state) state.textContent = dark ? "On" : "Off";
  }
  var themeBound = false;
  function initTheme() {
    // The script is deferred, so it can run initTheme twice (once at load, once on
    // DOMContentLoaded). A second click listener would undo every toggle.
    if (themeBound) return;
    themeBound = true;
    var button = document.getElementById("theme-toggle");
    // Only a page that offers the control reads the stored choice.
    if (!button) return;
    button.addEventListener("click", function () {
      var next = themeIsDark() ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        window.localStorage.setItem("acme-theme", next);
      } catch (error) {
        /* The choice then lasts for this page only. */
      }
      syncThemeControl();
    });
    syncThemeControl();
  }

  /* -------------------------------------------------------------- toast */
  function toast(message, sticky) {
    var node = document.getElementById("toast");
    if (!node) return;
    /* The hidden region of the last action speaks the result for a screen
       reader, so the toast is only its picture: without this the message
       would be read twice. */
    node.setAttribute("aria-live", "off");
    node.innerHTML = "";
    var line = document.createElement("span");
    line.className = "toast-text";
    line.textContent = message || "";
    node.appendChild(line);
    if (sticky) {
      /* A refusal stays until it is dismissed. */
      var dismiss = document.createElement("button");
      dismiss.type = "button";
      dismiss.className = "toast-dismiss";
      dismiss.setAttribute("data-testid", "toast-dismiss");
      dismiss.setAttribute("aria-label", "Dismiss the message");
      dismiss.textContent = "×";
      dismiss.addEventListener("click", hideToast);
      node.appendChild(dismiss);
    }
    node.classList.toggle("toast-sticky", Boolean(sticky));
    node.classList.add("on");
    window.clearTimeout(toast.timer);
    if (!sticky) {
      toast.timer = window.setTimeout(function () {
        node.classList.remove("on");
      }, 2400);
    }
  }

  function hideToast() {
    var node = document.getElementById("toast");
    if (!node) return;
    window.clearTimeout(toast.timer);
    node.classList.remove("on", "toast-sticky");
  }

  /* ------------------------------------------------------- the last action */
  /* The result of the last action of the acting persona lives in a panel that
     opens from the bell in the header.  The bell carries a dot while the
     result has not been opened, the toast shows the one line of the result
     for a moment, and the hidden region announces the result to a screen
     reader whether the panel is open or not. */
  function liveRegion() {
    return document.getElementById(REGION_ID);
  }

  function feedbackPanel() {
    return document.getElementById(PANEL_ID);
  }

  function lastActionToggle() {
    return document.getElementById(TOGGLE_ID);
  }

  function markNewAction() {
    var dot = document.querySelector('[data-testid="last-action-dot"]');
    if (dot) dot.removeAttribute("hidden");
  }

  function clearNewAction() {
    var dot = document.querySelector('[data-testid="last-action-dot"]');
    if (dot) dot.setAttribute("hidden", "hidden");
  }

  function openPanel(moveFocus) {
    var panel = feedbackPanel();
    if (!panel) return;
    panel.hidden = false;
    var toggle = lastActionToggle();
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    clearNewAction();
    if (moveFocus) {
      var title = panel.querySelector(".feedback-panel-title");
      if (title) title.focus();
    }
  }

  function closePanel(restoreFocus) {
    var panel = feedbackPanel();
    if (!panel) return;
    panel.hidden = true;
    var toggle = lastActionToggle();
    if (!toggle) return;
    toggle.setAttribute("aria-expanded", "false");
    if (restoreFocus) toggle.focus();
  }

  function feedbackDetails(outcome) {
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
    return details;
  }

  function renderOutcome(outcome) {
    var accepted = outcome.status === "accepted";
    var message = outcome.message || "";
    var toggle = lastActionToggle();
    if (toggle) toggle.setAttribute("data-outcome", outcome.status || "denied");

    var panel = feedbackPanel();
    if (panel) {
      panel.setAttribute("data-outcome", outcome.status || "denied");
      panel.classList.toggle("feedback-accepted", accepted);
      panel.classList.toggle("feedback-denied", !accepted);
      var heading = panel.querySelector(".feedback-panel-title");
      if (heading) {
        heading.textContent = accepted ? "Last action" : "The action was refused";
      }
      var body = panel.querySelector(".feedback-panel-body");
      if (body) {
        body.innerHTML = "";
        var line = document.createElement("p");
        line.className = "feedback-message";
        line.setAttribute("data-testid", "feedback-message");
        line.textContent = message;
        body.appendChild(line);
        body.appendChild(feedbackDetails(outcome));
      }
    }

    /* The hidden region speaks the result, so a screen reader hears it even
       when the panel stays shut. */
    var live = liveRegion();
    if (live) live.textContent = message;

    markNewAction();
    if (accepted) {
      toast(message);
    } else {
      /* A refusal is shown without a click: the panel opens on the spot and
         the toast stays until it is dismissed. */
      openPanel(false);
      toast(message, true);
    }
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
       counts.  The banner, the panel of the last action and the theme stay. */
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
        renderOutcome(result.payload);
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
        renderOutcome({
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

  function initLastAction() {
    /* The bell of the last action and the panel it opens.  Both live outside
       the content of the screen, so they survive the reading of the page
       again after an action and are bound once. */
    var toggle = lastActionToggle();
    if (toggle && !toggle.getAttribute("data-bound")) {
      toggle.setAttribute("data-bound", "yes");
      toggle.addEventListener("click", function () {
        var panel = feedbackPanel();
        if (!panel) return;
        if (panel.hidden) {
          openPanel(true);
        } else {
          closePanel(true);
        }
      });
    }
    var close = document.querySelector('[data-testid="feedback-panel-close"]');
    if (close && !close.getAttribute("data-bound")) {
      close.setAttribute("data-bound", "yes");
      close.addEventListener("click", function () {
        closePanel(true);
      });
    }
  }

  document.addEventListener("keydown", function (event) {
    /* Escape closes the panel of the last action and gives the focus back to
       the bell that opened it. */
    if (event.key !== "Escape") return;
    var panel = feedbackPanel();
    if (!panel || panel.hidden) return;
    closePanel(true);
  });

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initLastAction();
    initUi();
  });
  // The script is deferred, so DOMContentLoaded may already have fired in
  // some embedding contexts; initTheme is idempotent, run it now as well.
  if (document.readyState !== "loading") {
    initTheme();
    initLastAction();
  }
})();
