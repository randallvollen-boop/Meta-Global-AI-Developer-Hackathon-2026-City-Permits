/* The guided tour of the ACME City demonstration.

   The tour walks one permit from the application to the public record, in the
   order of the written walkthrough.  It switches persona through the ordinary
   persona switch, opens the real screen, rings the control the person would
   press and explains in one or two lines what happens there and why it
   matters.  It never changes a record: it opens screens and points.

   The steps live in config/tour_steps.json and are served by /tour/steps.
   The overlay is built here, so the tour works on every page that loads
   this script.  The state of the tour lives in the session storage, so the
   tour survives the page change between two steps.  The auto-play lives in
   the same place, so the tour keeps playing across the page change as well:
   the viewer presses Auto-play once and the tour walks on by itself. */

(function () {
  "use strict";

  /* The engine is loaded once.  A second copy would answer the same click
     twice and start the tour twice. */
  if (window.acmeTour) return;

  var STEPS_URL = "/tour/steps";
  var ACTOR_URL = "/ui/actor";
  var STATE_KEY = "acme-tour";
  var AUTO_PLAY_MS = 9000;
  var COUNTDOWN_MS = 1000;

  var steps = null;
  var index = 0;
  var timer = null;
  var ticker = null;
  var deadline = 0;
  var stepMs = 0;
  var overlay = null;
  var bound = false;

  /* Where the tour is, and whether it plays on its own.  The state travels
     in the session storage: a step that opens another screen comes back to
     the same place, and the auto-play comes back with it. */
  var state = { active: false, index: 0, playing: false, intervalMs: 0 };

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

  /* The state of the tour is written whenever it changes, so the next screen
     finds the tour where it was left, playing or paused. */
  function persist() {
    writeState(state);
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
      '  <p class="tour-caption" data-testid="tour-caption" aria-live="polite"></p>',
      '  <p class="tour-warning" data-testid="tour-warning" hidden></p>',
      '  <p class="tour-note" id="tour-note" data-testid="tour-note" hidden></p>',
      '  <div class="tour-controls">',
      '    <button type="button" class="btn sm" data-tour-back data-testid="tour-back">Back</button>',
      '    <button type="button" class="btn sm" data-tour-play data-testid="tour-play">Auto-play</button>',
      '    <span class="tour-auto" data-testid="tour-auto" hidden>',
      '      <span class="tour-countdown" data-testid="tour-countdown" aria-live="off"></span>',
      '      <span class="tour-progress" data-testid="tour-progress" aria-hidden="true">',
      '        <span class="tour-progress-fill" data-testid="tour-progress-fill"></span>',
      '      </span>',
      '    </span>',
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
    if (!overlay) return null;
    return overlay.querySelector('[data-testid="' + name + '"]');
  }

  function note(text) {
    var element = part("tour-note");
    if (!element) return;
    element.textContent = text || "";
    element.hidden = !text;
  }

  function warning(text) {
    var element = part("tour-warning");
    if (!element) return;
    element.textContent = text || "";
    element.hidden = !text;
  }

  /* The note of the panel.  It explains why the tour does not play on its
     own, and it says when the tour has come to its end. */
  function paintNote() {
    var messages = [];
    if (reducedMotion()) {
      messages.push("Auto-play is off: the system asks for reduced motion. Press Next to go on.");
    }
    if (steps && index >= steps.length - 1) {
      messages.push("The tour is finished.");
    }
    if (!messages.length && index === 0) {
      messages.push("This is the first step.");
    }
    note(messages.join(" "));
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
    } else {
      play.disabled = false;
      play.removeAttribute("aria-describedby");
    }
    paintNote();
    if (!ring(current)) {
      warning("The control of this step is not on this screen.");
    } else {
      warning("");
    }
    /* The tour plays on across the page change: the state carries the wish
       of the viewer, and this screen starts the timer again.  The last step
       finishes the tour, so the timer stops there. */
    if (state.playing) {
      startAuto();
    } else {
      clearTimers();
      paintAuto();
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
    state.active = true;
    state.index = index;
    persist();
    /* The page is going away.  The wish to play on stays in the state, so
       the next screen carries the tour on without another click. */
    clearTimers();
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
      state.index = 0;
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

  /* ------------------------------------------------------------ auto play */

  /* The length of one step of the auto-play.  A test may shorten it with
     window.acmeTour.setInterval(ms), or with data-tour-interval on the tour
     root; the ordinary tour waits nine seconds for every step. */
  function autoPlayMs() {
    if (state.intervalMs > 0) return state.intervalMs;
    var attribute = intervalAttribute();
    if (attribute > 0) {
      state.intervalMs = attribute;
      persist();
      return attribute;
    }
    return AUTO_PLAY_MS;
  }

  function intervalAttribute() {
    var roots = [overlay, part("tour-panel"), document.body];
    for (var number = 0; number < roots.length; number++) {
      var root = roots[number];
      if (!root || !root.getAttribute) continue;
      var value = parseInt(root.getAttribute("data-tour-interval"), 10);
      if (isFinite(value) && value > 0) return value;
    }
    return 0;
  }

  /* The test hook: it shortens the step of the auto-play for the test only,
     and it travels with the state, so it holds across the page change. */
  function setAutoPlayMs(value) {
    var ms = parseInt(value, 10);
    if (!isFinite(ms) || ms <= 0) return autoPlayMs();
    state.intervalMs = ms;
    persist();
    if (state.playing) {
      /* The step changes at once, so the hook may be set while the tour
         plays and not only before it starts. */
      clearTimers();
      startAuto();
    }
    return ms;
  }

  function clearTimers() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    if (ticker !== null) {
      window.clearInterval(ticker);
      ticker = null;
    }
  }

  function startAuto() {
    if (timer !== null) return;
    if (reducedMotion() || (steps && index >= steps.length - 1)) {
      /* The tour may not play on its own: the system asks for reduced motion,
         or the tour has come to its last step. */
      state.playing = false;
      paintAuto();
      paintNote();
      persist();
      return;
    }
    var ms = autoPlayMs();
    state.playing = true;
    stepMs = ms;
    deadline = Date.now() + ms;
    timer = window.setInterval(goNext, ms);
    ticker = window.setInterval(countdown, COUNTDOWN_MS);
    paintAuto();
    countdown();
    persist();
  }

  function stopAuto() {
    clearTimers();
    state.playing = false;
    paintAuto();
    persist();
  }

  function toggleAuto() {
    if (state.playing) {
      stopAuto();
      return;
    }
    startAuto();
  }

  /* The button says what it does, and the countdown sits beside it. */
  function paintAuto() {
    var play = part("tour-play");
    if (play) play.textContent = state.playing ? "Pause" : "Auto-play";
    var auto = part("tour-auto");
    if (auto) auto.hidden = !state.playing;
    if (!state.playing) {
      var text = part("tour-countdown");
      if (text) text.textContent = "";
      var fill = part("tour-progress-fill");
      if (fill) fill.style.width = "0%";
    }
  }

  /* The countdown of the step.  It counts the seconds down and fills the
     thin bar, so the viewer sees how long the step still lasts.  The text
     changes every second, so it stays quiet for the screen reader: only the
     caption of the step is announced. */
  function countdown() {
    if (!state.playing) return;
    var ms = autoPlayMs();
    if (ms !== stepMs) {
      /* The step of the auto-play changed: the timer follows it. */
      clearTimers();
      startAuto();
      return;
    }
    var left = Math.max(0, deadline - Date.now());
    var text = part("tour-countdown");
    if (text) text.textContent = "Next in " + Math.ceil(left / 1000) + " s";
    var fill = part("tour-progress-fill");
    if (fill) {
      var done = ms > 0 ? Math.min(1, Math.max(0, 1 - left / ms)) : 1;
      fill.style.width = Math.round(done * 100) + "%";
    }
  }

  function exit() {
    stopAuto();
    state.active = false;
    state.index = 0;
    state.playing = false;
    clearState();
    if (overlay) {
      overlay.hidden = true;
      var ringBox = part("tour-ring");
      if (ringBox) ringBox.hidden = true;
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
    var saved = readState();
    if (!saved) return;
    if (saved.intervalMs > 0) state.intervalMs = saved.intervalMs;
    if (!saved.active) return;
    state.active = true;
    state.index = saved.index || 0;
    state.playing = !!saved.playing;
    index = state.index;
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

  window.acmeTour = {
    start: start,
    next: goNext,
    back: goBack,
    exit: exit,
    stop: stopAuto,
    setInterval: setAutoPlayMs,
    setAutoPlayMs: setAutoPlayMs
  };
})();
