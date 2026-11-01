/* The local script of the applicant help panel.

   The script is an enhancement, not a requirement: the panel works without
   it.  The question is an ordinary form post that re-renders the page with
   the answer, and on the application form the answer opens in a separate
   browsing context so the typed fields and files stay intact.

   When the script is present the question is sent in the background and the
   answer is rendered in place, a suggested question fills the box instead of
   navigating, and the launcher opens the assistant in a small window of its
   own.  Nothing here decides anything: the server answers from its own
   source bundle and the script only shows what it sent back. */

(function () {
  "use strict";

  /* The window the assistant opens in.  It keeps the name, so a second
     launcher reuses the same window. */
  var POPOUT_NAME = "acme-permit-help";
  var POPOUT_FEATURES = "width=420,height=680,noopener";
  var POPOUT_PATH = "/apply/help/panel";

  function panelOf(node) {
    if (!node || !node.closest) return null;
    return node.closest("[data-testid=help-panel]");
  }

  function contactHref(panel) {
    /* The contact page continues the conversation of the panel, so the
       question reaches the case the applicant was asking about. */
    var conversation = panel ? panel.getAttribute("data-help-conversation") : "";
    return "/city/contact" + (conversation ? "?conversation=" + conversation : "") + "#ask";
  }

  function popoutUrl(link) {
    /* The window opens the panel in the pop-out placement, and it keeps the
       context of the page it was opened from: the application the applicant
       was looking at. */
    var href = (link && link.getAttribute("href")) || POPOUT_PATH;
    var url = href.split("#")[0];
    if (url.indexOf("placement=") === -1) {
      url += (url.indexOf("?") === -1 ? "?" : "&") + "placement=popout";
    }
    return url;
  }

  function openPopout(event) {
    event.preventDefault();
    window.open(popoutUrl(event.currentTarget), POPOUT_NAME, POPOUT_FEATURES);
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
    /* The link to the contact page carries the conversation, so the request
       reaches the case the applicant was asking about. */
    panel.setAttribute("data-help-conversation", conversationId || "");
  }

  function citationLabel(citation) {
    /* The readable label of the passage, never its raw identifier. */
    var label = citation.title || citation.source_id || "";
    if (citation.citation && label.indexOf(citation.citation) === -1) {
      label = label + ": " + citation.citation;
    }
    return label;
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
      item.setAttribute("data-outcome", turn.outcome || "");
      item.setAttribute("data-mode", turn.mode || "");
      var question = document.createElement("p");
      question.className = "help-question-text";
      question.textContent = turn.question;
      item.appendChild(question);
      var paragraphs = turn.paragraphs || [];
      if (paragraphs.length) {
        var label = document.createElement("p");
        label.className = "muted";
        label.setAttribute("data-testid", "help-answer-label");
        label.textContent = turn.label;
        item.appendChild(label);
      }
      if (turn.declined_text) {
        var declined = document.createElement("p");
        declined.setAttribute("data-testid", "help-declined");
        declined.setAttribute("data-reason", turn.reason || "");
        var head = document.createElement("strong");
        head.textContent = "The assistant did not answer.";
        declined.appendChild(head);
        declined.appendChild(document.createTextNode(" " + turn.declined_text));
        if (paragraphs.length) {
          declined.appendChild(
            document.createTextNode(
              " The rule text that matches your words is shown here instead."
            )
          );
        }
        declined.appendChild(document.createTextNode(" "));
        var ask = document.createElement("a");
        ask.setAttribute("href", contactHref(panel));
        ask.setAttribute("data-testid", "help-declined-link");
        ask.textContent = "Ask a person at the City";
        declined.appendChild(ask);
        item.appendChild(declined);
      }
      if (paragraphs.length) {
        var citations = document.createElement("ul");
        citations.className = "help-citations";
        citations.setAttribute("data-testid", "help-citations");
        for (var j = 0; j < paragraphs.length; j++) {
          var paragraph = paragraphs[j];
          var entry = document.createElement("li");
          if (paragraph.text && paragraph.text !== paragraph.quote) {
            var said = document.createElement("p");
            said.setAttribute("data-testid", "help-paragraph-text");
            said.textContent = paragraph.text;
            entry.appendChild(said);
          }
          var sources =
            paragraph.citations && paragraph.citations.length
              ? paragraph.citations
              : [paragraph];
          for (var k = 0; k < sources.length; k++) {
            var citation = sources[k];
            var details = document.createElement("details");
            var summary = document.createElement("summary");
            summary.setAttribute("data-testid", "help-citation");
            summary.textContent = citationLabel(citation);
            details.appendChild(summary);
            var quote = document.createElement("blockquote");
            quote.setAttribute("data-testid", "help-quote");
            quote.textContent = citation.quote;
            details.appendChild(quote);
            entry.appendChild(details);
          }
          citations.appendChild(entry);
        }
        item.appendChild(citations);
      } else {
        var none = document.createElement("p");
        none.setAttribute("data-testid", "help-no-match");
        none.textContent = panel.getAttribute("data-help-no-match") || "";
        item.appendChild(none);
      }
      if (turn.created_at) {
        var stamp = document.createElement("p");
        stamp.className = "muted";
        stamp.textContent = turn.created_at;
        item.appendChild(stamp);
      }
      list.appendChild(item);
    }
    region.innerHTML = "";
    region.appendChild(list);
  }

  function renderEscalation(panel, escalation) {
    var slot = panel.querySelector("[data-help-escalation-slot]");
    if (!slot) return;
    slot.innerHTML = "";
    if (!escalation || !escalation.offered) return;
    var prompt = document.createElement("p");
    prompt.className = "callout";
    prompt.setAttribute("role", "status");
    prompt.setAttribute("data-testid", "help-escalation-prompt");
    prompt.setAttribute("data-reason", escalation.reason || "");
    prompt.appendChild(document.createTextNode((escalation.text || "") + " "));
    var link = document.createElement("a");
    link.setAttribute("href", contactHref(panel));
    link.setAttribute("data-testid", "help-escalation-link");
    link.textContent = "Ask a person at the City";
    prompt.appendChild(link);
    slot.appendChild(prompt);
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
        renderEscalation(panel, result.payload.escalation);
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
    /* Every launcher opens the assistant in the small window of its own. */
    var launchers = document.querySelectorAll(
      "[data-help-popout], [data-testid=help-launcher]"
    );
    for (var i = 0; i < launchers.length; i++) {
      launchers[i].addEventListener("click", openPopout);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
