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
    function refresh() {
      if (!window.fetch || !window.FormData) { return; }
      var data = new FormData(form);
      data.delete("csrf_token");
      form.querySelectorAll("input[type=file]").forEach(function (input) {
        data.delete(input.name);
        if (input.files && input.files.length) { data.append("have__" + input.name.replace("file__", ""), "1"); }
      });
      fetch(form.getAttribute("data-check-url"), { method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (state) {
          if (!state) { return; }
          if (statusLine) {
            statusLine.textContent = state.status || "";
            statusLine.setAttribute("data-complete", state.can_submit ? "true" : "false");
          }
          renderNeeds(state);
        }).catch(function () { /* the server still checks on submit */ });
    }
    // After a refused Submit the errors stay up; each one clears as the person fixes it.
    // Completeness never disables Submit.  Only a Must fix on a complete application does,
    // and only after Check my application or a refused Submit.
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
      button.disabled = !ready;
      if (ready) {
        button.removeAttribute("aria-describedby");
        if (why) { why.hidden = true; }
      } else {
        button.setAttribute("aria-describedby", "submit-anyway-why");
        if (why) { why.hidden = false; }
      }
    }
    function ensureOverride() {
      var wrap = form.querySelector("[data-override]");
      if (!wrap) {
        wrap = document.createElement("div");
        wrap.setAttribute("data-override", "");
        var label = document.createElement("label");
        label.htmlFor = "override-reason";
        label.textContent = "Why submit now";
        var box = document.createElement("textarea");
        box.id = "override-reason";
        box.name = "override_reason";
        box.setAttribute("data-testid", "why-submit-now");
        box.maxLength = 500;
        var button = document.createElement("button");
        button.type = "submit";
        button.name = "intent";
        button.value = "override";
        button.className = "btn";
        button.setAttribute("data-testid", "submit-anyway");
        button.disabled = true;
        button.setAttribute("aria-describedby", "submit-anyway-why");
        button.textContent = "Submit anyway";
        var why = document.createElement("p");
        why.id = "submit-anyway-why";
        why.setAttribute("data-testid", "submit-anyway-why");
        why.textContent = "Enter why submit now.";
        wrap.appendChild(label);
        wrap.appendChild(box);
        wrap.appendChild(button);
        wrap.appendChild(why);
        var save = form.querySelector("[data-testid='save-draft']");
        if (save && save.parentNode) { save.parentNode.insertBefore(wrap, save); }
        else { form.appendChild(wrap); }
      }
      wrap.hidden = false;
      var bound = document.getElementById("override-reason");
      if (bound && !bound.getAttribute("data-bound")) {
        bound.setAttribute("data-bound", "1");
        bound.addEventListener("input", syncAnyway);
      }
      syncAnyway();
    }
    function applyHold(review) {
      if (!submit) { return; }
      if (review.held) {
        submit.disabled = true;
        var why = document.getElementById("submit-held-why");
        if (!why) {
          why = document.createElement("p");
          why.id = "submit-held-why";
          why.setAttribute("data-testid", "submit-held-why");
          why.textContent = "Fix the items under Must fix, or use Submit anyway.";
          submit.insertAdjacentElement("afterend", why);
        }
        why.hidden = false;
        submit.setAttribute("aria-describedby", "submit-held-why");
        ensureOverride();
      } else {
        submit.disabled = false;
        submit.removeAttribute("aria-describedby");
        var heldWhy = document.getElementById("submit-held-why");
        if (heldWhy) { heldWhy.hidden = true; }
        var wrap = form.querySelector("[data-override]");
        if (wrap) { wrap.hidden = true; }
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
        row.textContent = item.sentence || "";
        if (item.feedback) {
          var note = document.createElement("span");
          note.setAttribute("data-testid", "presubmit-feedback");
          note.textContent = " " + item.feedback;
          row.appendChild(note);
        }
        section.appendChild(row);
      });
      return section;
    }
    function renderReview(review) {
      var root = form.querySelector("[data-presubmit-root]");
      if (!root) { return; }
      root.hidden = false;
      root.setAttribute("data-testid", "presubmit-panel");
      root.textContent = "";
      ["must_fix", "should_check", "looks_good"].forEach(function (key) {
        root.appendChild(groupSection(review, key));
      });
      if (review.assistant_note) {
        var note = document.createElement("p");
        note.setAttribute("data-testid", "assistant-note");
        note.textContent = review.assistant_note;
        root.appendChild(note);
      }
      applyHold(review);
    }
    function reviewData() {
      // The files stay on the request so the assistant can read a text file.
      // The review path is a read, so this does not spend the upload allowance.
      var data = new FormData(form);
      data.delete("csrf_token");
      data.set("intent", "review");
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
    var existingReason = document.getElementById("override-reason");
    if (existingReason) {
      if (!existingReason.getAttribute("data-bound")) {
        existingReason.setAttribute("data-bound", "1");
        existingReason.addEventListener("input", syncAnyway);
      }
      syncAnyway();
    }
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
    form.addEventListener("input", slow);
    form.addEventListener("change", function (event) {
      refresh();
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
    if (address) { address.addEventListener("input", debounce(locate, 300)); }
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
