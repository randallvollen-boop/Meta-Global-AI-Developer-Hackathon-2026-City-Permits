/* The local script of the ACME City demonstration interface.

   The script is an enhancement, not a requirement: every action works
   without it.  When it is present an action form is submitted in the
   background and the typed outcome of the action is rendered in the
   feedback region, so the user learns what changed, where it was written
   and whether a source or a consumer still has to acknowledge it. */

(function () {
  "use strict";

  var REGION_ID = "ui-feedback-region";

  function feedbackRegion() {
    var region = document.getElementById(REGION_ID);
    if (region) {
      return region;
    }
    region = document.createElement("section");
    region.id = REGION_ID;
    region.className = "feedback";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    region.setAttribute("data-testid", "feedback");
    var main = document.getElementById("main");
    if (main && main.parentNode) {
      main.parentNode.insertBefore(region, main);
    } else {
      document.body.insertBefore(region, document.body.firstChild);
    }
    return region;
  }

  function renderOutcome(region, outcome) {
    var accepted = outcome.status === "accepted";
    region.className = "feedback " + (accepted ? "feedback-accepted" : "feedback-denied");
    region.setAttribute("data-outcome", outcome.status || "denied");
    region.innerHTML = "";

    var title = document.createElement("h2");
    title.className = "feedback-title";
    title.textContent = accepted ? "Last action" : "The action was refused";
    region.appendChild(title);

    var message = document.createElement("p");
    message.className = "feedback-message";
    message.setAttribute("data-testid", "feedback-message");
    message.textContent = outcome.message || "";
    region.appendChild(message);

    var list = document.createElement("dl");
    list.className = "feedback-detail";
    var rows = [
      ["Destination", outcome.destination || "not applicable", "feedback-destination"],
      ["State", outcome.state || "not applicable", "feedback-state"],
      [
        "Pending",
        outcome.pending
          ? "yes, the source or the consumer has not acknowledged yet"
          : "no",
        "feedback-pending"
      ],
      [
        "Version",
        outcome.version === null || outcome.version === undefined
          ? "not applicable"
          : String(outcome.version),
        "feedback-version"
      ],
      ["Affected", (outcome.affected || []).join(", ") || "none", "feedback-affected"]
    ];
    rows.forEach(function (row) {
      var wrapper = document.createElement("div");
      var term = document.createElement("dt");
      term.textContent = row[0];
      var definition = document.createElement("dd");
      definition.setAttribute("data-testid", row[2]);
      definition.textContent = row[1];
      wrapper.appendChild(term);
      wrapper.appendChild(definition);
      list.appendChild(wrapper);
    });
    region.appendChild(list);
  }

  function submit(form) {
    var button = form.querySelector("button[type=submit]");
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    form.setAttribute("aria-busy", "true");
    fetch(form.action, {
      method: form.method || "post",
      body: new FormData(form),
      headers: {
        Accept: "application/json",
        "X-Requested-With": "acme-city-ui"
      },
      credentials: "same-origin",
      redirect: "follow"
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload };
        });
      })
      .then(function (result) {
        renderOutcome(feedbackRegion(), result.payload);
        if (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        }
        form.removeAttribute("aria-busy");
      })
      .catch(function () {
        renderOutcome(feedbackRegion(), {
          status: "denied",
          message: "The action could not be sent. Use the screen again to retry."
        });
        if (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        }
        form.removeAttribute("aria-busy");
      });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.classList || !form.classList.contains("action-form")) {
      return;
    }
    event.preventDefault();
    submit(form);
  });

  document.addEventListener("DOMContentLoaded", function () {
    var region = document.querySelector(".feedback");
    if (region && !region.id) {
      region.id = REGION_ID;
    }
  });
})();
