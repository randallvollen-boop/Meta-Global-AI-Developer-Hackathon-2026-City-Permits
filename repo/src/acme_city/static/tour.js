/* The guided tour of the ACME City demonstration.

   The tour walks one path through the City, in the order of the written
   walkthrough of that path.  Take the tour with no path named walks the
   fence, then the café, then the city.  A story step has no control: the
   panel sits in the centre and says why the case starts there.  The tour
   switches persona through the ordinary persona switch, opens the real
   screen, rings the control the person would press and says why that step
   happens.  It never changes a record: it opens screens and points.

   The steps live in config/tour_steps.json and are served by /tour/steps.
   The browser asks for the path it walks, so every path has its own tour
   and its own Auto-play.  The overlay is built here, so the
   tour works on every page that loads this script.  The state of the tour
   lives in the session storage, so the tour survives the page change between
   two steps and keeps the path it walks.  The auto-play lives in the same
   place, so the tour keeps playing across the page change as well: the
   viewer presses Auto-play once and the tour walks on by itself.

   One step may offer Start fresh: it creates a copy of the café case for
   the visitor, so the path works for every judge of the shared
   demonstration.  That is the only write the tour ever makes, and the server
   decides whether it may. */

(function () {
  "use strict";

  /* The engine is loaded once.  A second copy would answer the same click
     twice and start the tour twice. */
  if (window.acmeTour) return;

  var STEPS_URL = "/tour/steps";
  var AUDIO_MANIFEST_URL = "/ui/static/tour-audio/manifest.json";
  var AUDIO_ROOT = "/ui/static/tour-audio/";
  var ACTOR_URL = "/ui/actor";
  var FRESH_URL = "/walkthrough/start-fresh?format=json";
  var STATE_KEY = "acme-tour";
  var VOICE_KEY = "acme-tour-voice";
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
  var audioManifest = null;
  var audioManifestRequest = null;
  var audioElement = null;
  var voiceOn = false;

  /* Where the tour is, and whether it plays on its own.  The state travels
     in the session storage: a step that opens another screen comes back to
     the same place, and the auto-play comes back with it. */
  var state = { active: false, index: 0, playing: false, intervalMs: 0, path: "" };

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

  function readVoicePreference() {
    var store = memory();
    if (!store) return false;
    try {
      return store.getItem(VOICE_KEY) === "on";
    } catch (error) {
      return false;
    }
  }

  function writeVoicePreference(on) {
    var store = memory();
    if (!store) return;
    try {
      if (on) store.setItem(VOICE_KEY, "on");
      else store.removeItem(VOICE_KEY);
    } catch (error) {
      /* The visitor can still turn narration on for this screen. */
    }
  }

  /* A per-visitor café copy can disappear when the demonstration data is
     reset. Do not resume the saved tour into that missing case. */
  function clearMissingCaseState() {
    if (!document.body || document.body.getAttribute("data-case-missing") !== "true") return false;
    clearState();
    return true;
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
      '  <p class="tour-path" data-testid="tour-path"></p>',
      '  <p class="tour-count" data-testid="tour-count"></p>',
      '  <h2 class="tour-title" data-testid="tour-title"></h2>',
      '  <p class="tour-caption" data-testid="tour-caption" aria-live="polite"></p>',
      '  <p class="tour-muse" data-testid="tour-muse" hidden>',
      '    <span class="tour-muse-badge" data-testid="tour-muse-badge">Muse</span>',
      '    <span data-testid="tour-muse-line"></span>',
      '  </p>',
      '  <p class="tour-replay" data-testid="tour-replay" hidden></p>',
      '  <p class="tour-warning" data-testid="tour-warning" hidden></p>',
      '  <p class="tour-note" id="tour-note" data-testid="tour-note" hidden></p>',
      '  <p class="tour-fresh" data-testid="tour-fresh" hidden>',
      '    <button type="button" class="btn sm" data-tour-fresh data-testid="tour-fresh-button">Start fresh</button>',
      '    <span class="tour-fresh-note" data-testid="tour-fresh-note"></span>',
      '  </p>',
      '  <p class="tour-fill" data-testid="tour-fill-row" hidden>',
      '    <button type="button" class="btn sm" data-tour-fill data-testid="tour-fill">Fill in the story\'s answers</button>',
      '  </p>',
      '  <div class="tour-permit" data-testid="tour-permit-card" hidden></div>',
      '  <div class="tour-controls">',
      '    <button type="button" class="btn sm" data-tour-back data-testid="tour-back">Back</button>',
      '    <button type="button" class="btn sm" data-tour-voice data-testid="tour-voice" aria-pressed="false" hidden>Play voice</button>',
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
    overlay.querySelector("[data-tour-voice]").addEventListener("click", toggleVoice);
    overlay.querySelector("[data-tour-exit]").addEventListener("click", exit);
    overlay.querySelector("[data-tour-fresh]").addEventListener("click", startFresh);
    overlay.querySelector("[data-tour-fill]").addEventListener("click", fillStory);
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

  /* The Muse badge and the one line that says what Muse does on this step.
     A step that does not use Muse hides both. */
  function paintMuse(current) {
    var block = part("tour-muse");
    if (!block) return;
    var line = part("tour-muse-line");
    if (current.muse) {
      block.hidden = false;
      if (line) line.textContent = current.muse_line || "";
    } else {
      block.hidden = true;
      if (line) line.textContent = "";
    }
  }

  /* Fill the form that is already on the screen.  The values come from the
     step.  The button never submits the form and never presses Check. */
  function formOnScreen() {
    return document.querySelector("[data-portal-form]") || document.querySelector("form");
  }

  function setControl(form, name, value) {
    var nodes = form.querySelectorAll('[name="' + name + '"]');
    if (!nodes.length) return;
    var first = nodes[0];
    if (first.type === "radio") {
      for (var i = 0; i < nodes.length; i++) {
        var radio = nodes[i];
        radio.checked = radio.value === String(value);
        if (radio.checked) radio.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return;
    }
    if (first.type === "checkbox") {
      var on = value === "on" || value === true || value === "true" || value === "1";
      for (var j = 0; j < nodes.length; j++) {
        nodes[j].checked = on;
        nodes[j].dispatchEvent(new Event("change", { bubbles: true }));
      }
      return;
    }
    if (first.type === "file") return;
    first.value = value == null ? "" : String(value);
    first.dispatchEvent(new Event("input", { bubbles: true }));
    first.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function attachFile(form, name, file) {
    var input = form.querySelector('input[type="file"][name="' + name + '"]');
    if (!input || typeof DataTransfer === "undefined" || typeof File === "undefined") return;
    var made = new File([file.text || ""], file.name || "note.txt", { type: "text/plain" });
    var transfer = new DataTransfer();
    transfer.items.add(made);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /* A story arrival may fill only the pristine form the visitor was shown.
     Default selections count as pristine.  Any typed value, changed choice,
     or selected file belongs to the visitor and is never replaced. */
  function formIsPristine(form) {
    var controls = form.elements || [];
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i];
      if (!control || control.disabled) continue;
      var type = String(control.type || "").toLowerCase();
      if (type === "hidden" || type === "submit" || type === "button" || type === "reset") continue;
      if (type === "file") {
        if (control.files && control.files.length) return false;
        continue;
      }
      if (type === "checkbox" || type === "radio") {
        if (control.checked !== control.defaultChecked) return false;
        continue;
      }
      if (control.tagName === "SELECT") {
        for (var option = 0; option < control.options.length; option++) {
          var selectedByBrowser = option === 0 && control.selectedIndex === 0 &&
            !control.options[option].defaultSelected;
          if (control.options[option].selected !== control.options[option].defaultSelected && !selectedByBrowser) return false;
        }
        continue;
      }
      if (control.value !== control.defaultValue) return false;
    }
    return true;
  }

  function fillStory() {
    var current = step();
    var spec = current && current.fill;
    var form = formOnScreen();
    if (!spec || !form) return;
    /* The normal form change listeners provide live completeness and address
       lookup.  A tour fill is a local demonstration setup, not a visitor
       edit, and must not leave asynchronous requests racing the next persona
       switch.  The form listener recognizes this short-lived marker while
       still updating purely local controls such as conditional questions. */
    form.setAttribute("data-tour-filling", "true");
    try {
      var fields = spec.fields || {};
      var names = Object.keys(fields);
      names.sort(function (left, right) {
        var leftNode = form.querySelector('[name="' + left + '"]');
        var rightNode = form.querySelector('[name="' + right + '"]');
        var leftRadio = leftNode && leftNode.type === "radio" ? 0 : 1;
        var rightRadio = rightNode && rightNode.type === "radio" ? 0 : 1;
        return leftRadio - rightRadio;
      });
      for (var i = 0; i < names.length; i++) setControl(form, names[i], fields[names[i]]);
      var files = spec.files || {};
      Object.keys(files).forEach(function (name) { attachFile(form, name, files[name]); });
    } finally {
      form.removeAttribute("data-tour-filling");
    }
  }

  function fillStoryOnArrival(current) {
    var form = formOnScreen();
    if (!current || !current.fill || !form || !formIsPristine(form)) return;
    fillStory();
  }

  function paintFill(current) {
    var row = part("tour-fill-row");
    if (!row) return;
    row.hidden = !(current && current.fill);
  }

  /* The issued permit of this judge's café copy.  Names, documents and fees
     stay off the card.  The link opens the public search already filled in. */
  function paintPermit(current) {
    var card = part("tour-permit-card");
    if (!card) return;
    var permit = current && current.permit;
    card.textContent = "";
    if (!permit || !permit.number) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    var heading = document.createElement("h3");
    heading.textContent = permit.title || "Permit issued";
    card.appendChild(heading);
    function line(label, value) {
      var row = document.createElement("p");
      row.textContent = label + ": " + (value || "");
      card.appendChild(row);
    }
    line("Permit", permit.number);
    line("Address", permit.address);
    line("Parcel", permit.parcel);
    line("Outcome", permit.outcome);
    line("Conditions", permit.conditions);
    line("Date", permit.date);
    if (permit.search_line) {
      var search = document.createElement("p");
      search.setAttribute("data-testid", "tour-permit-search-line");
      search.textContent = permit.search_line;
      card.appendChild(search);
    }
    if (permit.search_href) {
      var link = document.createElement("a");
      link.href = permit.search_href;
      link.setAttribute("data-testid", "tour-permit-search");
      link.textContent = permit.search_label || "Search for my permit";
      card.appendChild(link);
    }
  }

  /* The note beside Start fresh, and the note that says a track needs no copy. */
  function paintCopy(current) {
    var fresh = part("tour-fresh");
    if (!fresh) return;
    var freshNote = part("tour-fresh-note");
    var freshButton = part("tour-fresh-button");
    var text = (current && current.copy_note) || "";
    if (current && current.fresh) {
      fresh.hidden = false;
      if (freshButton) {
        freshButton.hidden = false;
        freshButton.disabled = false;
      }
      if (freshNote) freshNote.textContent = text;
      return;
    }
    if (text) {
      fresh.hidden = false;
      if (freshButton) freshButton.hidden = true;
      if (freshNote) freshNote.textContent = text;
      return;
    }
    fresh.hidden = true;
    if (freshNote) freshNote.textContent = "";
  }

  /* The replay line is separate from the caption.  It is empty when live
     Muse can still answer, and the panel hides it then. */
  function paintReplay(current) {
    var block = part("tour-replay");
    if (!block) return;
    var text = current.replay_note || "";
    block.textContent = text;
    block.hidden = !text;
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

  /* The steps of one path.  The path is asked for by name, so every path
     has its own list and its own count. */
  function loadSteps(pathKey) {
    var key = pathKey || state.path || "";
    if (steps && key === state.path) return Promise.resolve(steps);
    var url = STEPS_URL + (key ? "?path=" + encodeURIComponent(key) : "");
    return fetch(url, { credentials: "same-origin" })
      .then(function (answer) {
        return answer.json();
      })
      .then(function (payload) {
        steps = (payload && payload.steps) || [];
        state.path = (payload && payload.path) || key;
        return steps;
      });
  }

  function step() {
    return steps && steps[index] ? steps[index] : null;
  }

  /* -------------------------------------------------------------- voice */

  function voiceKey(current) {
    if (!current || !current.id) return "";
    /* Bridges belong to the combined story, not to either adjacent track. */
    if (current.kind === "bridge") return String(current.id);
    return current.path_key ? String(current.path_key) + "-" + String(current.id) : "";
  }

  function clipFor(current) {
    if (!audioManifest) return "";
    var clip = audioManifest[voiceKey(current)];
    /* Filenames come from the local generated manifest, never from tour copy. */
    return typeof clip === "string" && /^[A-Za-z0-9_.-]+\\.mp3$/.test(clip) ? clip : "";
  }

  function loadAudioManifest() {
    if (audioManifestRequest) return audioManifestRequest;
    audioManifestRequest = fetch(AUDIO_MANIFEST_URL, { credentials: "same-origin" })
      .then(function (answer) {
        if (!answer.ok) throw new Error("The voice manifest is unavailable.");
        return answer.json();
      })
      .then(function (payload) {
        audioManifest = payload && typeof payload === "object" && !Array.isArray(payload)
          ? payload : {};
        return audioManifest;
      })
      .catch(function () {
        audioManifest = {};
        return audioManifest;
      })
      .then(function (manifest) {
        if (overlay && !overlay.hidden) paintVoice(step());
        return manifest;
      });
    return audioManifestRequest;
  }

  function voicePlayer() {
    if (audioElement) return audioElement;
    audioElement = document.createElement("audio");
    audioElement.preload = "auto";
    audioElement.hidden = true;
    document.body.appendChild(audioElement);
    return audioElement;
  }

  function stopVoice() {
    if (!audioElement) return;
    audioElement.pause();
    try {
      audioElement.currentTime = 0;
    } catch (error) {
      /* A clip that has not loaded has no time to reset. */
    }
  }

  function playVoice(current, clip) {
    if (!voiceOn || !clip) return;
    var player = voicePlayer();
    var source = AUDIO_ROOT + clip;
    if (player.getAttribute("src") !== source) player.setAttribute("src", source);
    try {
      player.currentTime = 0;
    } catch (error) {
      /* Playback still begins when the browser has loaded the clip. */
    }
    var playing = player.play();
    if (playing && playing.catch) playing.catch(function () {});
  }

  function paintVoice(current) {
    var button = part("tour-voice");
    if (!button) return;
    var clip = clipFor(current);
    button.hidden = !clip;
    if (!clip) {
      stopVoice();
      return;
    }
    button.textContent = voiceOn ? "Mute voice" : "Play voice";
    button.setAttribute("aria-pressed", voiceOn ? "true" : "false");
    if (voiceOn) playVoice(current, clip);
  }

  function toggleVoice() {
    var current = step();
    var clip = clipFor(current);
    if (!clip) return;
    voiceOn = !voiceOn;
    writeVoicePreference(voiceOn);
    if (!voiceOn) stopVoice();
    paintVoice(current);
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

  /* --------------------------------------------------------------- fresh */

  /* The token of the page.  The server decides whether the write may. */
  function formToken() {
    var engine = document.querySelector("script[data-tour-csrf]");
    if (engine) return String(engine.getAttribute("data-tour-csrf") || "");
    var field = document.querySelector('[data-testid="tour-csrf"]');
    return field ? String(field.value || "") : "";
  }

  /* Start fresh asks the server for a copy of the café case for this
     visitor.  The server may refuse, and then the panel says why. */
  function startFresh() {
    var button = part("tour-fresh-button");
    var freshNote = part("tour-fresh-note");
    if (button) button.disabled = true;
    if (freshNote) freshNote.textContent = "Making your copy of the café case.";
    fetch(FRESH_URL, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: "csrf_token=" + encodeURIComponent(formToken())
    })
      .then(function (answer) {
        return answer.json().then(function (payload) {
          return { ok: answer.ok, payload: payload || {} };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          if (button) button.disabled = false;
          if (freshNote) {
            freshNote.textContent = result.payload.message || "The copy could not be made.";
          }
          return;
        }
        /* The copy is made.  The page is read again, so the new tasks of
           the Data Steward are on the screen and the tour goes on. */
        window.location.reload();
      })
      .catch(function () {
        if (button) button.disabled = false;
        if (freshNote) freshNote.textContent = "The copy could not be made.";
      });
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
    part("tour-path").textContent = current.path_title || "";
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
    paintCopy(current);
    paintFill(current);
    fillStoryOnArrival(current);
    paintPermit(current);
    paintVoice(current);
    paintNote();
    paintMuse(current);
    paintReplay(current);
    /* A story intro and the line between tracks name no control.  The panel
       sits in the centre, and the tour does not warn that a control is missing. */
    var panel = part("tour-panel");
    var centred = !current.target;
    if (panel) panel.classList.toggle("is-centred", centred);
    if (centred) {
      var ringBox = part("tour-ring");
      if (ringBox) ringBox.hidden = true;
      warning("");
    } else if (!ring(current)) {
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
    stopVoice();
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

  /* Start the tour of one path.  A path with no name opens the full story
     the server builds: the fence, then the café, then the city. */
  function start(pathKey) {
    var key = pathKey || "";
    state.path = key;
    steps = null;
    loadSteps(key).then(function () {
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
      if (fill) fill.style.transform = "scaleX(0)";
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
      /* The bar grows by a scale, so the browser animates a transform
         instead of a width. */
      fill.style.transform = "scaleX(" + done.toFixed(4) + ")";
    }
  }

  function exit() {
    stopAuto();
    stopVoice();
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

  /* Any button marked data-tour-start opens the tour, whenever it appears.
     The name of the attribute is the path the tour walks; an empty name
     opens the path the server offers by default. */
  function bindStarters() {
    document.addEventListener("click", function (event) {
      var button = event.target && event.target.closest
        ? event.target.closest("[data-tour-start]")
        : null;
      if (button) start(button.getAttribute("data-tour-start") || "");
    });
  }

  function resume() {
    var saved = readState();
    if (!saved) return;
    if (saved.intervalMs > 0) state.intervalMs = saved.intervalMs;
    if (saved.path) state.path = saved.path;
    if (!saved.active) return;
    state.active = true;
    state.index = saved.index || 0;
    state.playing = !!saved.playing;
    index = state.index;
    loadSteps(state.path).then(show);
  }

  function init() {
    if (bound) return;
    bound = true;
    if (clearMissingCaseState()) return;
    ensureStyles();
    voiceOn = readVoicePreference();
    loadAudioManifest();
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
