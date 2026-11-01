/* The replay of a recorded agent run.

   The engine of the City works a case in one request, so the steps of a run
   are complete when the screen is read again.  This script replays those
   recorded steps on the step graph, level by level, so the operator sees the
   order the agent worked in.  It never claims to be a live run: the line
   above the graph says it is a replay, and the states it shows are the
   states the run recorded.

   A reader who asked for less motion sees the recorded states at once, and
   a screen in a background tab waits until the operator comes back. */
(function () {
  "use strict";

  /* The states a card may hold.  One of them is on the card at a time. */
  var STATES = ["idle", "ok", "warn", "block", "pending", "running"];

  /* How long one step of the replay stands on the screen. */
  var STEP_MS = 180;

  var DOT = '<span class="agent-dag-dot"></span>';
  var SPINNER = '<svg aria-hidden="true"><use href="#i-loader"/></svg>';

  function reducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  function cards(scope) {
    return Array.prototype.slice.call(
      scope.querySelectorAll("[data-testid='agent-dag-node']")
    );
  }

  function columns(block) {
    return Array.prototype.slice.call(
      block.querySelectorAll("[data-testid='agent-dag-level']")
    );
  }

  function setState(card, state, word, icon) {
    var kept = card.className.split(/\s+/).filter(function (name) {
      return name && STATES.indexOf(name) === -1;
    });
    kept.push(state);
    card.className = kept.join(" ");
    card.setAttribute("data-state", state);
    var label = card.querySelector(".agent-dag-state");
    if (label && word) label.textContent = word;
    var mark = card.querySelector(".st");
    if (mark && icon !== null) mark.innerHTML = icon;
  }

  function runButtons(block) {
    /* The run buttons of the panel the graph stands in.  They are off while
       the replay runs, so a second run cannot start in the middle of it. */
    var scope = block.closest ? block.closest(".panel") : null;
    if (!scope) return [];
    return Array.prototype.slice.call(
      scope.querySelectorAll(
        "[data-testid='agent-run-one'],[data-testid='agent-run-all']"
      )
    );
  }

  function replay(block) {
    if (block.getAttribute("data-replaying") === "true") return;
    var steps = [];
    columns(block).forEach(function (column) {
      var recorded = cards(column).filter(function (card) {
        return card.getAttribute("data-state") !== "idle";
      });
      if (!recorded.length) return;
      steps.push(
        recorded.map(function (card) {
          var label = card.querySelector(".agent-dag-state");
          var mark = card.querySelector(".st");
          return {
            card: card,
            state: card.getAttribute("data-state"),
            word: label ? label.textContent : "",
            icon: mark ? mark.innerHTML : ""
          };
        })
      );
    });
    if (!steps.length) return;
    /* A reader who asked for less motion reads the recorded states at once,
       so no card ever shows a spinner. */
    if (reducedMotion()) return;

    var status = block.querySelector("[data-testid='agent-progress-status']");
    var finalLine = status
      ? status.getAttribute("data-final-status") || status.textContent
      : "";
    var buttons = runButtons(block).map(function (button) {
      var was = button.disabled;
      button.disabled = true;
      return { button: button, was: was };
    });
    block.setAttribute("data-replaying", "true");
    steps.forEach(function (step) {
      step.forEach(function (entry) {
        setState(entry.card, "pending", "Waiting", DOT);
      });
    });
    if (status) status.textContent = "Replaying recorded steps";

    var index = 0;
    function settle() {
      block.removeAttribute("data-replaying");
      buttons.forEach(function (entry) {
        entry.button.disabled = entry.was;
      });
      if (status) status.textContent = finalLine;
    }
    function tick() {
      /* A screen in a background tab waits: the replay carries on when the
         operator comes back to it. */
      if (document.hidden) {
        window.setTimeout(tick, 200);
        return;
      }
      if (index >= steps.length) {
        settle();
        return;
      }
      var step = steps[index];
      step.forEach(function (entry) {
        setState(entry.card, "running", "Running", SPINNER);
      });
      window.setTimeout(function () {
        step.forEach(function (entry) {
          setState(entry.card, entry.state, entry.word, entry.icon);
        });
        index += 1;
        window.setTimeout(tick, STEP_MS);
      }, STEP_MS);
    }
    tick();
  }

  /* The script of the page asks for the replay after a run of an agent. */
  document.addEventListener("acme:agent-run", function () {
    var block = document.querySelector("[data-run-progress]");
    if (block) replay(block);
  });
})();
