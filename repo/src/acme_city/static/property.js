/* Property master enhancements: locator suggestions and the town map.
   Progressive enhancement only. Without this script the address field is a
   plain text box and the map is a static picture whose parcels are links. */
(function () {
  "use strict";

  function debounce(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  function initSuggest() {
    document.querySelectorAll("input[data-suggest-url]").forEach(function (input) {
      var list = input.list;
      if (!list || !window.fetch) { return; }
      var ask = debounce(function () {
        var text = input.value.trim();
        if (text.length < 3) { return; }
        fetch(input.getAttribute("data-suggest-url") + "?text=" + encodeURIComponent(text), {
          credentials: "same-origin", headers: { Accept: "application/json" }
        }).then(function (r) { return r.ok ? r.json() : { suggestions: [] }; })
          .then(function (body) {
            list.innerHTML = "";
            (body.suggestions || []).forEach(function (item) {
              var option = document.createElement("option");
              option.value = item.text;
              list.appendChild(option);
            });
          }).catch(function () { /* the plain form still works */ });
      }, 200);
      input.addEventListener("input", ask);
    });
  }

  function initMap(wrap) {
    var svg = wrap.querySelector("svg.gis-town");
    if (!svg) { return; }
    var extent = (svg.getAttribute("data-extent") || "0 0 960 700").split(" ").map(Number);
    var view = extent.slice();
    var tools = wrap.querySelector(".map-tools");
    var card = wrap.querySelector(".map-card");
    if (tools) { tools.hidden = false; }
    function apply() { svg.setAttribute("viewBox", view.join(" ")); }
    function zoom(factor, cx, cy) {
      var w = Math.min(extent[2], Math.max(extent[2] / 12, view[2] * factor));
      var h = w * extent[3] / extent[2];
      cx = cx === undefined ? view[0] + view[2] / 2 : cx;
      cy = cy === undefined ? view[1] + view[3] / 2 : cy;
      view = [cx - w / 2, cy - h / 2, w, h];
      clamp();
      apply();
    }
    function clamp() {
      view[0] = Math.max(extent[0], Math.min(view[0], extent[0] + extent[2] - view[2]));
      view[1] = Math.max(extent[1], Math.min(view[1], extent[1] + extent[3] - view[3]));
    }
    wrap.querySelectorAll("[data-map-zoom]").forEach(function (button) {
      button.addEventListener("click", function () {
        var kind = button.getAttribute("data-map-zoom");
        if (kind === "reset") { view = extent.slice(); apply(); } else { zoom(kind === "in" ? 0.6 : 1.6); }
      });
    });
    svg.addEventListener("wheel", function (event) {
      event.preventDefault();
      zoom(event.deltaY < 0 ? 0.85 : 1.15);
    }, { passive: false });
    var drag = null;
    svg.addEventListener("pointerdown", function (event) {
      drag = { x: event.clientX, y: event.clientY, moved: false };
    });
    svg.addEventListener("pointermove", function (event) {
      if (!drag) { return; }
      var dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) < 4 && !drag.moved) { return; }
      drag.moved = true;
      var box = svg.getBoundingClientRect();
      view[0] -= dx * view[2] / box.width;
      view[1] -= dy * view[3] / box.height;
      drag.x = event.clientX; drag.y = event.clientY;
      clamp(); apply();
    });
    window.addEventListener("pointerup", function () { setTimeout(function () { drag = null; }, 0); });
    svg.addEventListener("keydown", function (event) {
      var step = view[2] * 0.1;
      if (event.key === "+") { zoom(0.8); } else if (event.key === "-") { zoom(1.25); }
      else if (event.key === "ArrowLeft") { view[0] -= step; clamp(); apply(); }
      else if (event.key === "ArrowRight") { view[0] += step; clamp(); apply(); }
      else if (event.key === "ArrowUp") { view[1] -= step; clamp(); apply(); }
      else if (event.key === "ArrowDown") { view[1] += step; clamp(); apply(); }
    });
    function show(number) {
      var row = document.querySelector('[data-parcel-row="' + number + '"]');
      if (!row || !card) { return; }
      var cells = row.querySelectorAll("td");
      var apps = cells[2] ? cells[2].textContent.trim() : "-";
      card.innerHTML = "";
      var title = document.createElement("strong");
      title.textContent = "Parcel " + number;
      card.appendChild(title);
      var info = document.createElement("p");
      info.textContent = "Site address " + (cells[0] ? cells[0].textContent.trim() : "-") +
        "; zoning " + (cells[1] ? cells[1].textContent.trim() : "-") + "; applications " + apps + ".";
      card.appendChild(info);
      var link = document.createElement("a");
      link.href = "/property/" + number;
      link.textContent = "Open property record";
      link.className = "btn sm primary";
      card.appendChild(link);
      card.hidden = false;
    }
    svg.querySelectorAll("a").forEach(function (anchor) {
      anchor.addEventListener("click", function (event) {
        if (drag && drag.moved) { event.preventDefault(); return; }
        var group = anchor.querySelector("[data-parcel]");
        if (!group) { return; }
        event.preventDefault();
        svg.querySelectorAll(".gis-parcel.is-picked").forEach(function (g) { g.classList.remove("is-picked"); });
        group.classList.add("is-picked");
        show(group.getAttribute("data-parcel"));
      });
    });
    var focus = svg.getAttribute("data-focus");
    if (focus) {
      var target = svg.querySelector('[data-parcel="' + focus + '"] path');
      if (target) {
        var b = target.getBBox();
        var w = Math.max(b.width * 5, extent[2] / 4);
        var h = w * extent[3] / extent[2];
        view = [b.x + b.width / 2 - w / 2, b.y + b.height / 2 - h / 2, w, h];
        clamp(); apply();
        show(focus);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initSuggest();
    document.querySelectorAll("[data-map]").forEach(initMap);
  });
})();

/* Applicant portal enhancements: live completeness, "Did you mean", drag and drop.
   Without this script the form still posts: the server checks every submit. */
(function () {
  "use strict";
  function debounce(fn, ms) {
    var timer = null;
    return function () { var a = arguments; clearTimeout(timer); timer = setTimeout(function () { fn.apply(null, a); }, ms); };
  }
  // The sample addresses beside the address field.  Picking one fills the
  // field and sends the same events a typed address sends, so the locator
  // checks the address and the completeness of the form is read again.
  function initSampleAddresses(form, address) {
    var button = form.querySelector("[data-testid='sample-address-button']");
    var list = form.querySelector("[data-testid='sample-address-list']");
    if (!button || !list || !address) { return; }
    function open() {
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
    }
    function close() {
      list.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }
    button.addEventListener("click", function () {
      if (list.hidden) { open(); } else { close(); }
    });
    list.querySelectorAll("[data-address]").forEach(function (option) {
      option.addEventListener("click", function () {
        address.value = option.getAttribute("data-address") || "";
        address.dispatchEvent(new Event("input", { bubbles: true }));
        address.dispatchEvent(new Event("change", { bubbles: true }));
        close();
      });
    });
  }

  function init(form) {
    var statusLine = form.querySelector("[data-status]");
    var summary = form.querySelector("[data-error-summary]");
    var submit = form.querySelector("[data-testid='submit-application']");
    var dym = form.querySelector("[data-did-you-mean]");
    var address = form.querySelector("[name='address_text']");
    // A review on the screen means the hold must be asked about again while
    // the applicant edits.  Without it the browser keeps the hold of a
    // review the applicant has already answered, and Submit stays off.
    var reviewShown = false;
    // The assistant's note and its notes on the rules are kept when the
    // live check answers again without the assistant.
    var lastNote = "";
    var lastFeedback = {};
    // Set from the page the server rendered, before any live check.  A check
    // that cannot see the files (they are empty after a reload) must not
    // clear a hold the server already showed.
    var serverHeld = form.getAttribute("data-server-held") === "true";
    function setDisabled(button, off) {
      if (!button) { return; }
      // The property alone is not enough in every browser: a button the
      // server rendered as disabled stays grey until the attribute is gone.
      button.disabled = !!off;
      if (off) { button.setAttribute("disabled", ""); }
      else { button.removeAttribute("disabled"); }
    }
    function showNode(node, on) {
      if (!node) { return; }
      node.hidden = !on;
      if (on) { node.removeAttribute("hidden"); }
      else { node.setAttribute("hidden", ""); }
    }
    function markProvided(data, keepChosenFiles) {
      // A reload leaves every file input empty.  The copy on the draft, and
      // a tick for "Sent to the City separately", still counts as provided.
      form.querySelectorAll("input[type=file]").forEach(function (input) {
        var type = input.name.replace(/^file__/, "");
        var row = input.closest(".doc-row");
        var chosen = !!(input.files && input.files.length);
        if (!chosen || !keepChosenFiles) { data.delete(input.name); }
        if (chosen || (row && row.getAttribute("data-added") === "true")) {
          data.append("have__" + type, "1");
        }
        var sep = row && row.querySelector("[data-sent-separately]");
        if (sep && sep.checked) { data.set("sent_separately__" + type, "on"); }
      });
      data.set("sent_separately_posted", "1");
      var certify = form.querySelector("[name='certification_accepted']");
      if (certify && certify.checked) { data.set("certification_accepted", "on"); }
    }
    function refresh() {
      if (!window.fetch || !window.FormData) { return; }
      var data = new FormData(form);
      data.delete("csrf_token");
      if (reviewShown) { data.set("review", "1"); }
      markProvided(data, false);
      fetch(form.getAttribute("data-check-url"), { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (state) {
          if (!state) { return; }
          if (statusLine) {
            statusLine.textContent = state.status || "";
            statusLine.setAttribute("data-complete", state.can_submit ? "true" : "false");
          }
          renderNeeds(state);
          if (state.review) { renderReview(state.review, state.can_submit); }
        }).catch(function () { /* the server still checks on submit */ });
    }
    // After a refused Submit the errors stay up; each one clears as the person fixes it.
    // Completeness alone never disables Submit.  Only a Must fix on a complete
    // application does, and only after Check my application or a refused Submit.
    // A check that calls a held application incomplete does not lift that hold.
    function renderNeeds(state) {
      if (!summary) { return; }
      var anchors = {};
      (state.blocking || []).forEach(function (item) { anchors[item.anchor] = true; });
      summary.querySelectorAll("li[data-anchor]").forEach(function (li) {
        li.hidden = !anchors[li.getAttribute("data-anchor")];
      });
      form.querySelectorAll("[data-error-for]").forEach(function (msg) {
        var anchor = msg.getAttribute("data-error-for");
        msg.hidden = !anchors[anchor];
        var control = document.getElementById(anchor);
        if (control) {
          if (anchors[anchor]) { control.setAttribute("aria-invalid", "true"); } else { control.removeAttribute("aria-invalid"); }
        }
        var wrap = control && control.closest(".field, .doc-row, fieldset");
        if (wrap) { wrap.classList.toggle("needed", !!anchors[anchor]); }
      });
      var any = Object.keys(anchors).length > 0;
      summary.hidden = !any;
    }
    function syncAnyway() {
      var box = document.getElementById("override-reason");
      var button = form.querySelector("[data-testid='submit-anyway']");
      var why = document.getElementById("submit-anyway-why");
      if (!box || !button) { return; }
      var ready = box.value.trim().length > 0;
      setDisabled(button, !ready);
      if (ready) {
        button.removeAttribute("aria-describedby");
        if (why) { why.hidden = true; }
      } else {
        button.setAttribute("aria-describedby", "submit-anyway-why");
        if (why) { why.hidden = false; }
      }
    }
    function bindReason() {
      var bound = document.getElementById("override-reason");
      if (!bound || bound.getAttribute("data-bound")) { return; }
      bound.setAttribute("data-bound", "1");
      bound.addEventListener("input", syncAnyway);
      bound.addEventListener("change", syncAnyway);
    }
    function ensureOverride() {
      // The block is always in the page: the browser only shows it while the
      // hold is on, so there is one markup and not two.  Showing it does not
      // depend on a live check: the server already rendered it for a hold.
      var field = form.querySelector("[data-override-field]");
      showNode(field, true);
      var group = form.querySelector("[data-override-action]");
      showNode(group, true);
      bindReason();
      syncAnyway();
    }
    function holdNotice() {
      // The note that says why Submit application is off.  It sits with the
      // block, not inside the row of the buttons.
      var why = document.getElementById("submit-held-why");
      if (!why) {
        why = document.createElement("p");
        why.id = "submit-held-why";
        why.className = "hold-why";
        why.setAttribute("data-testid", "submit-held-why");
        why.textContent = "Fix the items under Must fix, or use Submit anyway.";
        var field = form.querySelector("[data-override-field]");
        var buttons = form.querySelector(".form-buttons");
        var anchor = field || buttons;
        if (anchor && anchor.parentNode) { anchor.parentNode.insertBefore(why, anchor); }
        else { form.appendChild(why); }
      }
      return why;
    }
    function applyHold(review, canSubmit) {
      if (!submit) { return; }
      var hold = !!review.held;
      // An incomplete answer is not "no longer held".  After a reload the
      // file inputs are empty; that must not hide the block the server showed.
      if (!hold && serverHeld && canSubmit === false) { hold = true; }
      if (hold) {
        serverHeld = true;
        setDisabled(submit, true);
        var why = holdNotice();
        showNode(why, true);
        submit.setAttribute("aria-describedby", "submit-held-why");
        ensureOverride();
      } else {
        serverHeld = false;
        form.removeAttribute("data-server-held");
        setDisabled(submit, false);
        submit.removeAttribute("aria-describedby");
        showNode(document.getElementById("submit-held-why"), false);
        showNode(form.querySelector("[data-override-field]"), false);
        showNode(form.querySelector("[data-override-action]"), false);
      }
    }
    function groupSection(review, key) {
      var section = document.createElement("section");
      section.setAttribute("data-testid", key.replace("_", "-"));
      var title = document.createElement("h2");
      title.textContent = (review.labels && review.labels[key]) || "";
      section.appendChild(title);
      var items = review[key] || [];
      if (!items.length) {
        var none = document.createElement("p");
        none.textContent = "None.";
        section.appendChild(none);
        return section;
      }
      items.forEach(function (item) {
        var row = document.createElement("p");
        row.setAttribute("data-testid", "presubmit-item");
        row.setAttribute("data-rule-id", item.rule_id || "");
        row.textContent = item.sentence || "";
        if (item.feedback) {
          var note = document.createElement("span");
          note.className = "muse-note";
          note.setAttribute("data-testid", "presubmit-feedback");
          var badge = document.createElement("span");
          badge.className = "tour-muse-badge";
          badge.setAttribute("data-testid", "presubmit-muse-badge");
          badge.textContent = "Muse";
          var lead = document.createElement("span");
          lead.setAttribute("data-testid", "presubmit-muse-lead");
          lead.textContent = "Muse says:";
          note.appendChild(badge);
          note.appendChild(document.createTextNode(" "));
          note.appendChild(lead);
          note.appendChild(document.createTextNode(" " + item.feedback));
          row.appendChild(note);
        }
        section.appendChild(row);
      });
      return section;
    }
    function renderReview(review, canSubmit) {
      var root = form.querySelector("[data-presubmit-root]");
      if (!root) { return; }
      reviewShown = true;
      // The live check answers with the rules alone.  What the assistant
      // said about them is kept, so the note does not blink away.
      if (review.assistant_note) { lastNote = review.assistant_note; }
      review.assistant_note = lastNote;
      ["must_fix", "should_check", "looks_good"].forEach(function (key) {
        (review[key] || []).forEach(function (item) {
          var id = item.rule_id || "";
          if (item.feedback) { lastFeedback[id] = item.feedback; }
          else if (lastFeedback[id]) { item.feedback = lastFeedback[id]; }
        });
      });
      root.hidden = false;
      root.setAttribute("data-testid", "presubmit-panel");
      root.textContent = "";
      ["must_fix", "should_check", "looks_good"].forEach(function (key) {
        root.appendChild(groupSection(review, key));
      });
      if (review.assistant_note) {
        var note = document.createElement("p");
        note.setAttribute("data-testid", "assistant-note");
        var badge = document.createElement("span");
        badge.className = "tour-muse-badge";
        badge.setAttribute("data-testid", "presubmit-muse-badge");
        badge.textContent = "Muse";
        var lead = document.createElement("span");
        lead.setAttribute("data-testid", "presubmit-muse-lead");
        lead.textContent = "Muse says:";
        note.appendChild(badge);
        note.appendChild(document.createTextNode(" "));
        note.appendChild(lead);
        note.appendChild(document.createTextNode(" " + review.assistant_note));
        root.appendChild(note);
      }
      applyHold(review, canSubmit);
    }
    // Read the review the server rendered, so a page that was answered by
    // the server (a refused Submit) asks about the hold again as well.
    function rememberRenderedReview() {
      var root = form.querySelector("[data-presubmit-root]");
      if (!root || root.hidden) { return; }
      reviewShown = true;
      var note = root.querySelector("[data-testid='assistant-note']");
      if (note) { lastNote = note.textContent; }
      root.querySelectorAll("[data-testid='presubmit-item']").forEach(function (row) {
        var said = row.querySelector("[data-testid='presubmit-feedback']");
        if (said) { lastFeedback[row.getAttribute("data-rule-id") || ""] = said.textContent; }
      });
    }
    function reviewData() {
      // A file the applicant just chose stays on the request so the assistant
      // can read a text file.  The review path is a read, so this does not
      // spend the upload allowance.  A file already on the draft is named
      // instead: the input is empty after a reload.
      var data = new FormData(form);
      data.delete("csrf_token");
      data.set("intent", "review");
      markProvided(data, true);
      return data;
    }
    function runReview() {
      if (!window.fetch || !window.FormData) { return; }
      fetch(form.getAttribute("data-review-url"), {
        method: "POST",
        body: reviewData(),
        credentials: "same-origin",
        headers: { Accept: "application/json" }
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (review) { if (review) { renderReview(review); } })
        .catch(function () { /* the form still posts when this script is absent */ });
    }
    form.addEventListener("submit", function (event) {
      var button = event.submitter;
      if (!button || button.getAttribute("data-testid") !== "check-application") { return; }
      if (!window.fetch || !window.FormData) { return; }
      event.preventDefault();
      runReview();
    });
    // Follow the review the server rendered, before any live check.  A hold
    // shows the reason and Submit anyway, and Submit application stays off.
    // Anything else leaves Submit application usable.  The script may disable
    // Submit anyway until a reason is typed; if this script never runs, the
    // button stays usable and the form posts the reason.
    bindReason();
    if (serverHeld) {
      setDisabled(submit, true);
      showNode(document.getElementById("submit-held-why"), true);
      if (submit) { submit.setAttribute("aria-describedby", "submit-held-why"); }
      ensureOverride();
    } else if (submit) {
      setDisabled(submit, false);
      submit.removeAttribute("aria-describedby");
    }
    rememberRenderedReview();
    if (summary) { summary.focus(); }
    function setPill(row, input) {
      var pill = row.querySelector("[data-testid='doc-status']");
      var sep = row.querySelector("[data-sent-separately]");
      var hasFile = input && input.files && input.files.length > 0;
      var added = row.getAttribute("data-added") === "true";
      var text = (hasFile || added) ? "Added" : (sep && sep.checked ? "Sent separately" : "Add file");
      pill.textContent = text;
      pill.className = "pill " + (text === "Add file" ? "warn" : "ok");
    }
    var slow = debounce(refresh, 250);
    function tourIsFilling() {
      return form.getAttribute("data-tour-filling") === "true";
    }
    form.addEventListener("input", function () {
      if (!tourIsFilling()) { slow(); }
    });
    form.addEventListener("change", function (event) {
      if (!tourIsFilling()) { refresh(); }
      var input = event.target;
      if (input && input.type === "file") {
        var row = input.closest(".doc-row");
        if (row) {
          setPill(row, input);
        }
      } else if (input && input.hasAttribute && input.hasAttribute("data-sent-separately")) {
        var drow = input.closest(".doc-row");
        if (drow) { setPill(drow, drow.querySelector("input[type=file]")); }
      }
    });
    function locate() {
      if (!address || !dym || !window.fetch) { return; }
      var text = address.value.trim();
      if (text.length < 3) { dym.textContent = ""; return; }
      fetch(form.getAttribute("data-locate-url") + "?text=" + encodeURIComponent(text), { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (body) {
          if (!body) { return; }
          dym.textContent = body.message || "";
        }).catch(function () {});
    }
    if (address) {
      var delayedLocate = debounce(locate, 300);
      address.addEventListener("input", function () {
        if (!tourIsFilling()) { delayedLocate(); }
      });
    }
    initSampleAddresses(form, address);
    form.querySelectorAll("[data-drop-zone]").forEach(function (zone) {
      var row = zone.closest(".doc-row");
      var input = zone.querySelector("input[type=file]");
      var hint = zone.querySelector("[data-drop-hint]");
      if (hint) { hint.hidden = false; }
      ["dragenter", "dragover"].forEach(function (name) {
        row.addEventListener(name, function (e) { e.preventDefault(); row.classList.add("is-over"); });
      });
      ["dragleave", "drop"].forEach(function (name) {
        row.addEventListener(name, function (e) { e.preventDefault(); row.classList.remove("is-over"); });
      });
      row.addEventListener("drop", function (e) {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length && window.DataTransfer) {
          var dt = new DataTransfer();
          dt.items.add(e.dataTransfer.files[0]);
          input.files = dt.files;
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    });
    // Suggest-as-you-type uses the same datalist mechanism.
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-portal-form]").forEach(init);
  });
})();
