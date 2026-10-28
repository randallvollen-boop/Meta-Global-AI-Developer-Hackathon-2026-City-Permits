/* The local script of the applicant screens.  It only enhances: every control
   works without it (the question groups of the deck-or-fence form are all
   shown and the server ignores the one that does not apply; a file is added
   or replaced by choosing it and pressing Save draft or Submit).

   What it adds: it hides the question group that does not apply, and it names
   a chosen file and any problem with its type or size straight away.  The
   server checks the file again; nothing here decides anything. */
(function () {
  "use strict";

  var MAX = 5 * 1024 * 1024;
  var OK = /\.(pdf|png|jpe?g|txt)$/i;

  function toggleGroups(form) {
    var choices = form.querySelectorAll("[data-choice-input]");
    if (!choices.length) return;
    var groups = form.querySelectorAll("[data-when-key]");
    function apply() {
      var current = {};
      choices.forEach(function (input) {
        if (input.checked) current[input.name] = input.value;
      });
      groups.forEach(function (group) {
        var key = group.getAttribute("data-when-key");
        var want = group.getAttribute("data-when-value");
        var show = current[key] === want;
        group.classList.toggle("is-inactive", !show);
        group.hidden = !show;
        var note = group.querySelector(".when-note");
        if (note) note.hidden = show;
      });
    }
    choices.forEach(function (input) { input.addEventListener("change", apply); });
    apply();
  }

  function describeFiles(form) {
    form.querySelectorAll("[data-doc-input]").forEach(function (input) {
      input.addEventListener("change", function () {
        var out = input.closest(".drop-zone").querySelector("[data-doc-chosen]");
        var row = input.closest(".doc-row");
        var old = row.querySelector("[data-js-problem]");
        if (old) old.remove();
        if (!out) return;
        var file = input.files && input.files[0];
        if (!file) { out.textContent = ""; return; }
        var problem = "";
        if (!OK.test(file.name)) problem = "That file type is not accepted; add a PDF, PNG, JPG or plain text file.";
        else if (file.size > MAX) problem = "The file is larger than 5 MB.";
        if (problem) {
          out.textContent = "";
          var p = document.createElement("p");
          p.className = "field-error";
          p.setAttribute("role", "alert");
          p.setAttribute("data-js-problem", "true");
          p.textContent = problem;
          row.insertBefore(p, row.querySelector(".doc-status-line"));
        } else {
          out.textContent = "Chosen: " + file.name + ". It is added when you save a draft or submit.";
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-portal-form]").forEach(function (form) {
      toggleGroups(form);
      describeFiles(form);
    });
  });
})();
