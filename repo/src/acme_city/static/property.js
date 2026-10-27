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
  function init(form) {
    var banner = form.querySelector("[data-banner]");
    var card = form.querySelector("[data-testid='completeness-banner']");
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
          banner.textContent = state.banner;
          card.classList.toggle("ok", state.complete);
          card.classList.toggle("warn", !state.complete);
          card.setAttribute("data-complete", state.complete ? "true" : "false");
          if (submit) { submit.disabled = !state.can_submit; }
        }).catch(function () { /* the server still checks on submit */ });
    }
    var slow = debounce(refresh, 250);
    form.addEventListener("input", slow);
    form.addEventListener("change", function (event) {
      refresh();
      var input = event.target;
      if (input && input.type === "file") {
        var row = input.closest(".doc-row");
        if (row) {
          var pill = row.querySelector("[data-testid='doc-status']");
          var has = input.files && input.files.length > 0;
          pill.textContent = has ? "Added" : "Add file";
          pill.className = "pill " + (has ? "ok" : "warn");
        }
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
