/* The guided tour of the ACME City demonstration.

   The tour walks one permit from the application to the public record, in the
   order of the written walkthrough.  It switches persona through the ordinary
   persona switch, opens the real screen, rings the control the person would
   press and explains in one or two lines what happens there and why it
   matters.  It never changes a record: it opens screens and points.

   The steps live in config/tour_steps.json and are served by /tour/steps.
   The overlay is built here, so the tour works on every page that loads
   this script.  The state of the tour lives in the session storage, so the
   tour survives the page change between two steps. */

(function () {
  "use strict";

  /* The engine is loaded once.  A second copy would answer the same click
     twice and start the tour twice. */
  if (window.acmeTour) return;

  var STEPS_URL = "/tour/steps";
  var ACTOR_URL = "/ui/actor";
  var STATE_KEY = "acme-tour";
  var AUTO_PLAY_MS = 9000;

  var steps = null;
  var index = 0;
  var timer = null;
  var overlay = null;
  var bound = false;

  /* ------------------------------------------------------------- storage */

  function memory() {
    try {
      return window.sessionStorage;
    } catch (error) {
      return null;
    }
  }

  function readState() {
    var store = memory();
    if (!store) return null;
    try {
      return JSON.parse(store.getItem(STATE_KEY) || "null");
    } catch (error) {
      return null;
    }
  }

  function writeState(value) {
    var store = memory();
    if (!store) return;
    try {
      store.setItem(STATE_KEY, JSON.stringify(value));
    } catch (error) {
      /* The tour still runs; it only forgets its place. */
    }
  }

  function clearState() {
    var store = memory();
    if (!store) return;
    try {
      store.removeItem(STATE_KEY);
    } catch (error) {
      /* Nothing to clear. */
    }
  }

  function reducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  }

  /* -------------------------------------------------------------- overlay */

  function build() {
    if (overlay) return overlay;
    var root = document.createElement("div");
    root.className = "tour-overlay";
    root.setAttribute("data-testid", "tour-overlay");
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", "Take the tour");
    root.innerHTML = [
      '<div class="tour-ring" data-testid="tour-ring" hidden></div>',
      '<div class="tour-panel" data-testid="tour-panel">',
      '  <p class="tour-count" data-testid="tour-count"></p>',
      '  <h2 class="tour-title" data-testid="tour-title"></h2>',
      '  <p class="tour-caption" data-testid="tour-caption"></p>',
      '  <p class="tour-warning" data-testid="tour-warning" hidden></p>',
      '  <p class="tour-note" id="tour-note" data-testid="tour-note" hidden></p>',
      '  <div class="tour-controls">',
      '    <button type="button" class="btn sm" data-tour-back data-testid="tour-back">Back</button>',
      '    <button type="button" class="btn sm" data-tour-play data-testid="tour-play">Auto-play</button>',
      '    <button type="button" class="btn sm primary" data-tour-next data-testid="tour-next">Next</button>',
      '    <button type="button" class="btn sm quiet" data-tour-exit data-testid="tour-exit">Exit</button>',
      '  </div>',
      '</div>'
    ].join("\n");
    document.body.appendChild(root);
    overlay = root;
    overlay.querySelector("[data-tour-back]").addEventListener("click", goBack);
    overlay.querySelector("[data-tour-next]").addEventListener("click", goNext);
    overlay.querySelector("[data-tour-play]").addEventListener("click", toggleAuto);
    overlay.querySelector("[data-tour-exit]").addEventListener("click", exit);
    return overlay;
  }

  function part(name) {
    return overlay.querySelector('[data-testid="' + name + '"]');
  }

  function note(text) {
    var element = part("tour-note");
    element.textContent = text || "";
    element.hidden = !text;
  }

  function warning(text) {
    var element = part("tour-warning");
    element.textContent = text || "";
    element.hidden = !text;
  }

  /* --------------------------------------------------------------- steps */

  function loadSteps() {
    if (steps) return Promise.resolve(steps);
    return fetch(STEPS_URL, { credentials: "same-origin" })
      .then(function (answer) {
        return answer.json();
      })
      .then(function (payload) {
        steps = (payload && payload.steps) || [];
        return steps;
      });
  }

  function step() {
    return steps && steps[index] ? steps[index] : null;
  }

  /* ----------------------------------------------------------- highlight */

  function ring(current) {
    var box = part("tour-ring");
    var target = null;
    try {
      target = document.querySelector(current.target);
    } catch (error) {
      target = null;
    }
    if (!target) {
      box.hidden = true;
      return false;
    }
    if (target.scrollIntoView) {
      target.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
    }
    place(target);
    return true;
  }

  /* Put the ring around the control.  The place is kept in the style of the
     ring itself, so the ring is right even before the stylesheet arrives. */
  function place(target) {
    var box = part("tour-ring");
    var where = target.getBoundingClientRect();
    box.hidden = false;
    box.style.position = "fixed";
    box.style.top = Math.round(where.top - 6) + "px";
    box.style.left = Math.round(where.left - 6) + "px";
    box.style.width = Math.round(where.width + 12) + "px";
    box.style.height = Math.round(where.height + 12) + "px";
  }

  /* The ring follows the control while the page moves under it. */
  function follow() {
    if (!overlay || overlay.hidden) return;
    var current = step();
    if (!current) return;
    var target = null;
    try {
      target = document.querySelector(current.target);
    } catch (error) {
      target = null;
    }
    if (target) place(target);
  }

  /* --------------------------------------------------------------- show */

  function show() {
    var current = step();
    if (!current) {
      exit();
      return;
    }
    build();
    overlay.hidden = false;
    part("tour-count").textContent = "Step " + (index + 1) + " of " + steps.length;
    part("tour-title").textContent = current.title || "";
    part("tour-caption").textContent = current.caption || "";
    part("tour-next").textContent = index === steps.length - 1 ? "Finish" : "Next";
    var back = part("tour-back");
    back.disabled = index === 0;
    var play = part("tour-play");
    if (reducedMotion()) {
      play.disabled = true;
      play.setAttribute("aria-describedby", "tour-note");
      note("Auto-play is off: the system asks for reduced motion. Press Next to go on.");
    } else {
      play.disabled = false;
      play.removeAttribute("aria-describedby");
      note(index === 0 ? "This is the first step." : "");
    }
    if (!ring(current)) {
      warning("The control of this step is not on this screen.");
    } else {
      warning("");
    }
  }

  /* -------------------------------------------------------------- moves */

  function switchPersona(actorId, next) {
    return fetch(ACTOR_URL, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: "actor_id=" + encodeURIComponent(actorId) + "&next=" + encodeURIComponent(next)
    });
  }

  function goTo(number) {
    if (!steps || number < 0 || number >= steps.length) return;
    index = number;
    writeState({ active: true, index: index });
    var current = step();
    var target = current.path;
    if (!current.actor_id) {
      window.location.href = target;
      return;
    }
    switchPersona(current.actor_id, target)
      .catch(function () {
        /* The screen still opens; the persona may be the wrong one. */
      })
      .then(function () {
        window.location.href = target;
      });
  }

  function start() {
    loadSteps().then(function () {
      index = 0;
      goTo(0);
    });
  }

  function goNext() {
    if (!steps) return;
    if (index + 1 >= steps.length) {
      exit();
      return;
    }
    goTo(index + 1);
  }

  function goBack() {
    if (!steps || index <= 0) return;
    goTo(index - 1);
  }

  function stopAuto() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    if (overlay) {
      var play = part("tour-play");
      if (play) play.textContent = "Auto-play";
    }
  }

  function toggleAuto() {
    if (timer !== null) {
      stopAuto();
      return;
    }
    if (reducedMotion()) {
      note("Auto-play is off: the system asks for reduced motion. Press Next to go on.");
      return;
    }
    timer = window.setInterval(goNext, AUTO_PLAY_MS);
    part("tour-play").textContent = "Pause";
  }

  function exit() {
    stopAuto();
    clearState();
    if (overlay) {
      overlay.hidden = true;
      part("tour-ring").hidden = true;
    }
  }

  /* --------------------------------------------------------------- wire */

  /* The stylesheet of the tour travels with the script, so the overlay is
     right on every page that carries the engine. */
  function ensureStyles() {
    if (document.querySelector('link[data-tour-styles]')) return;
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/ui/static/tour.css";
    link.setAttribute("data-tour-styles", "");
    document.head.appendChild(link);
  }

  /* Any button marked data-tour-start opens the tour, whenever it appears. */
  function bindStarters() {
    document.addEventListener("click", function (event) {
      var button = event.target && event.target.closest
        ? event.target.closest("[data-tour-start]")
        : null;
      if (button) start();
    });
  }

  function resume() {
    var state = readState();
    if (!state || !state.active) return;
    index = state.index || 0;
    loadSteps().then(show);
  }

  function init() {
    if (bound) return;
    bound = true;
    ensureStyles();
    bindStarters();
    window.addEventListener("scroll", follow, { passive: true });
    window.addEventListener("resize", follow);
    resume();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.acmeTour = { start: start, next: goNext, back: goBack, exit: exit, stop: stopAuto };
})();
