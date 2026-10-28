/* The local script of the applicant help panel.

   The script is an enhancement, not a requirement: the panel works without
   it.  The question is an ordinary form post that re-renders the page with
   the answer, and on the application form the answer opens in a separate
   browsing context so the typed fields and files stay intact.

   When the script is present the question is sent in the background and the
   answer is rendered in place, and a suggested question fills the box
   instead of navigating.  Nothing here decides anything: the server answers
   from its own source bundle and the script only shows what it sent back. */

(function () {
  "use strict";

  function panelOf(node) {
    if (!node || !node.closest) return null;
    return node.closest("[data-testid=help-panel]");
  }

  function syncConversation(panel, conversationId, version) {
    if (!panel) return;
    var identifiers = panel.querySelectorAll('input[name="conversation_id"]');
    for (var i = 0; i < identifiers.length; i++) {
      identifiers[i].value = conversationId;
    }
    var versions = panel.querySelectorAll('input[name="conversation_version"]');
    for (var i = 0; i < versions.length; i++) {
      versions[i].value = String(version);
    }
  }

  function renderTurns(panel, payload) {
    var region = panel.querySelector("[data-help-conversation]");
    if (!region) return;
    var list = document.createElement("ol");
    list.className = "help-turns";
    list.setAttribute("data-testid", "help-turns");
    var turns = payload.turns || [];
    for (var i = 0; i < turns.length; i++) {
      var turn = turns[i];
      var item = document.createElement("li");
      item.setAttribute("data-testid", "help-turn");
      item.setAttribute("data-outcome", turn.outcome);
      var question = document.createElement("p");
      question.className = "help-question-text";
      question.textContent = turn.question;
      item.appendChild(question);
      var label = document.createElement("p");
      label.className = "muted";
      label.setAttribute("data-testid", "help-answer-label");
      label.textContent = turn.label;
      item.appendChild(label);
      if (turn.paragraphs && turn.paragraphs.length) {
        var citations = document.createElement("ul");
        citations.className = "help-citations";
        citations.setAttribute("data-testid", "help-citations");
        for (var j = 0; j < turn.paragraphs.length; j++) {
          var paragraph = turn.paragraphs[j];
          var entry = document.createElement("li");
          var details = document.createElement("details");
          var summary = document.createElement("summary");
          summary.setAttribute("data-testid", "help-citation");
          summary.textContent = paragraph.source_id;
          if (paragraph.citation) summary.textContent += " — " + paragraph.citation;
          details.appendChild(summary);
          var quote = document.createElement("blockquote");
          quote.setAttribute("data-testid", "help-quote");
          quote.textContent = paragraph.quote;
          details.appendChild(quote);
          entry.appendChild(details);
          citations.appendChild(entry);
        }
        item.appendChild(citations);
      } else {
        var none = document.createElement("p");
        none.setAttribute("data-testid", "help-no-match");
        none.textContent = panel.getAttribute("data-help-no-match") || "";
        item.appendChild(none);
      }
      list.appendChild(item);
    }
    region.innerHTML = "";
    region.appendChild(list);
  }

  function showRefusal(form, message) {
    var region = document.createElement("p");
    region.className = "action-denied";
    region.setAttribute("role", "alert");
    region.setAttribute("data-testid", "help-error");
    region.textContent = message;
    if (form.parentNode) form.parentNode.insertBefore(region, form);
  }

  function askInPlace(event, form) {
    event.preventDefault();
    var panel = panelOf(form);
    fetch(form.getAttribute("action"), {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          showRefusal(
            form,
            (result.payload && result.payload.message) || "The question was refused."
          );
          return;
        }
        syncConversation(
          panel,
          result.payload.conversation_id,
          result.payload.conversation_version
        );
        renderTurns(panel, result.payload);
      })
      .catch(function () {
        /* The ordinary post is the fallback: it works without this script. */
        form.submit();
      });
  }

  function init() {
    var forms = document.querySelectorAll("form[data-help-form]");
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      if (form.getAttribute("action") !== "/apply/help") continue;
      form.addEventListener("submit", function (event) {
        askInPlace(event, this);
      });
    }
    var chips = document.querySelectorAll("a[data-help-suggestion]");
    for (var i = 0; i < chips.length; i++) {
      chips[i].addEventListener("click", function (event) {
        var panel = panelOf(this);
        if (!panel) return;
        var field = panel.querySelector("[data-testid=help-question]");
        if (!field) return;
        event.preventDefault();
        field.value = this.getAttribute("data-help-suggestion") || "";
        field.focus();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
