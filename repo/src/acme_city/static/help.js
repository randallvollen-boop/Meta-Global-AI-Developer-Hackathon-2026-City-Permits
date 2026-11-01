/* The local script of the applicant help panel.

   The script is an enhancement, not a requirement: without it the launcher
   is an ordinary link to the panel page, and the question is an ordinary
   form post that re-renders that page.

   With the script the assistant opens in a panel over the page.  The page
   stays where it is: nothing navigates, the fields and the files the
   applicant typed stay exactly as they were, and the panel holds the same
   assistant as the page of its own - the same endpoints, the same
   conversation, the same citations.

   Nothing here decides anything: the server answers from its own source
   bundle and the script only shows what it sent back. */

(function () {
  "use strict";

  /* The panel of the assistant.  The page of its own and the panel that
     slides up over the page are the same panel, fetched from one place. */
  var PANEL_PATH = "/apply/help/panel";

  /* The controls the keyboard may reach inside the open panel.  The summary
     of a disclosure is one of them: it is in the tab order of the browser. */
  var FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

  /* The open panel, the control that opened it, and the conversation it
     holds. */
  var host = null;
  var sheet = null;
  var opener = null;
  var loaded = false;
  var conversation = "";

  function hostElement() {
    if (!host) host = document.getElementById("help-panel-host");
    return host;
  }

  function sheetElement() {
    if (!sheet) sheet = document.querySelector("[data-testid=help-panel-sheet]");
    return sheet;
  }

  function panelOf(node) {
    if (!node || !node.closest) return null;
    return node.closest("[data-testid=help-panel]");
  }

  function panelUrl(link) {
    /* The panel is fetched from the place the launcher points at, so the
       panel knows the case and the permit type of the page it was opened
       from.  The conversation of the applicant travels with it. */
    var href = (link && link.getAttribute("href")) || PANEL_PATH;
    var url = href.split("#")[0];
    var separator = url.indexOf("?") === -1 ? "?" : "&";
    if (url.indexOf("placement=") === -1) {
      var box = hostElement();
      var placement = box ? box.getAttribute("data-help-placement") : "";
      if (placement) url += separator + "placement=" + encodeURIComponent(placement);
    }
    if (conversation && url.indexOf("conversation=") === -1) {
      url += (url.indexOf("?") === -1 ? "?" : "&") +
        "conversation=" + encodeURIComponent(conversation);
    }
    return url;
  }

  function contactHref(panel) {
    /* The contact page continues the conversation of the panel, so the
       question reaches the case the applicant was asking about. */
    var talk = panel ? panel.getAttribute("data-help-conversation") : "";
    return "/city/contact" + (talk ? "?conversation=" + talk : "") + "#ask";
  }

  function focusableItems() {
    var box = sheetElement();
    if (!box) return [];
    return Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), function (el) {
      return el.getClientRects().length > 0;
    });
  }

  function focusPanel() {
    var items = focusableItems();
    if (items.length) items[0].focus();
  }

  function showLauncher(visible) {
    var launchers = document.querySelectorAll("[data-help-panel-launcher]");
    for (var i = 0; i < launchers.length; i++) {
      launchers[i].hidden = !visible;
      launchers[i].setAttribute("aria-expanded", visible ? "false" : "true");
    }
  }

  function openPanel(trigger) {
    var box = hostElement();
    if (!box) return false;
    opener = trigger;
    box.hidden = false;
    showLauncher(false);
    focusPanel();
    return true;
  }

  function closePanel() {
    var box = hostElement();
    if (!box || box.hidden) return;
    box.hidden = true;
    showLauncher(true);
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }

  function panelIsOpen() {
    var box = hostElement();
    return !!box && !box.hidden;
  }

  function rememberConversation(conversationId) {
    /* The conversation belongs to the applicant and it stays with the page:
       the address carries it, so a reload opens the panel on the same
       conversation. */
    conversation = conversationId || "";
    try {
      var url = new URL(window.location.href);
      if (conversation) url.searchParams.set("help", conversation);
      else url.searchParams.delete("help");
      window.history.replaceState(window.history.state, "", url.toString());
    } catch (error) {
      /* The address is a convenience; the panel still holds the talk. */
    }
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
    rememberConversation(conversationId);
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
        declined.appendChild(document.createTextNode(turn.declined_text + " "));
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
          var said = document.createElement("p");
          said.setAttribute("data-testid", "help-paragraph-text");
          said.textContent = paragraph.sentence;
          entry.appendChild(said);
          var name = document.createElement("p");
          name.className = "muted";
          name.setAttribute("data-testid", "help-citation-label");
          name.textContent = paragraph.label;
          entry.appendChild(name);
          var details = document.createElement("details");
          var summary = document.createElement("summary");
          summary.setAttribute("data-testid", "help-citation");
          summary.textContent = "Show the rule text";
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

  function preparePanel(panel) {
    /* The panel of the page is fetched after the page is read, so its form
       and its questions are wired here, not when the page was read. */
    if (!panel) return;
    var form = panel.querySelector("form[data-help-form]");
    if (form && !form.getAttribute("data-help-ready")) {
      form.setAttribute("data-help-ready", "1");
      if (form.getAttribute("action") === "/apply/help") {
        form.addEventListener("submit", function (event) {
          askInPlace(event, this);
        });
      }
    }
    var chips = panel.querySelectorAll("a[data-help-suggestion]");
    for (var i = 0; i < chips.length; i++) {
      if (chips[i].getAttribute("data-help-ready")) continue;
      chips[i].setAttribute("data-help-ready", "1");
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

  function loadPanel(url) {
    var box = sheetElement();
    if (!box) return;
    var body = box.querySelector("[data-help-panel-body]");
    if (!body) return;
    var request = url + (url.indexOf("?") === -1 ? "?" : "&") + "fragment=1";
    fetch(request, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then(function (response) {
        if (!response.ok) throw new Error("the panel could not be read");
        return response.text();
      })
      .then(function (html) {
        body.innerHTML = html;
        loaded = true;
        var panel = body.querySelector("[data-testid=help-panel]");
        preparePanel(panel);
        if (panel) {
          var field = panel.querySelector("[data-testid=help-question]");
          if (field) field.focus();
        }
      })
      .catch(function () {
        /* The panel page is one click away: the applicant is never left
           without the assistant. */
        body.innerHTML = "";
        var note = document.createElement("p");
        note.className = "muted";
        note.setAttribute("data-testid", "help-panel-error");
        note.textContent = "The assistant could not be opened here.";
        body.appendChild(note);
        var link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("data-testid", "help-panel-link");
        link.textContent = "Open the assistant on its own page";
        body.appendChild(link);
      });
  }

  function openFromLauncher(event) {
    var link = event.currentTarget;
    if (!hostElement()) return;
    /* A click with a key held means "open this elsewhere": the launcher is
       an ordinary link, and the panel page is one click away. */
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (event.button !== 0) return;
    event.preventDefault();
    if (!openPanel(link)) return;
    if (!loaded) loadPanel(panelUrl(link));
  }

  function trapFocus(event) {
    var items = focusableItems();
    if (!items.length) return;
    var box = sheetElement();
    var first = items[0];
    var last = items[items.length - 1];
    var active = document.activeElement;
    if (!box.contains(active)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function init() {
    var panels = document.querySelectorAll("[data-testid=help-panel]");
    for (var i = 0; i < panels.length; i++) {
      preparePanel(panels[i]);
    }
    /* Every launcher of the assistant opens the panel over the page. */
    var launchers = document.querySelectorAll(
      "[data-help-panel-open], [data-testid=help-launcher]"
    );
    for (var i = 0; i < launchers.length; i++) {
      launchers[i].addEventListener("click", openFromLauncher);
    }
    var closers = document.querySelectorAll("[data-help-panel-close]");
    for (var i = 0; i < closers.length; i++) {
      closers[i].addEventListener("click", function (event) {
        event.preventDefault();
        closePanel();
      });
    }
    document.addEventListener("keydown", function (event) {
      if (!panelIsOpen()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closePanel();
        return;
      }
      if (event.key === "Tab") trapFocus(event);
    });
    /* The conversation of the page is the one the address names. */
    try {
      conversation = new URL(window.location.href).searchParams.get("help") || "";
    } catch (error) {
      conversation = "";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
