# Changes to the in-app help

Date: 2026-11-02
Branch: `docs/final-pass`

The in-app help is read from three places: `repo/config/help_content.json`
(the hub, the tutorial and the how-to guides), the overlays in
`repo/config/help_content.d/` (one file per lane that owns a part of the help)
and `repo/config/ui_glossary.json` (the glossary of the information
popovers). Every label quoted below was copied from the screen it names, in
`repo/src/acme_city/templates`, `repo/src/acme_city/static` and
`repo/src/acme_city/ui`.

## `repo/config/help_content.json`

| Entry | What changed | Before | After |
| --- | --- | --- | --- |
| `tutorial.replay_note` | The claim that no model is called | "No model is called when you follow these steps." | A step that may call Muse for a live answer says so on the screen, and the label of that answer says so too |
| `tutorial.sections[persona_applicant].steps[9]` | The label of the answer of the assistant | The answer shows "Recorded demo answer" and cites the rule | The label says where the answer came from: "Recorded demo answer" for a stored answer and "Muse Spark (live)" for a live one |
| `howto.guides[ask-the-help-assistant-and-ask-the-city].steps[3]` | The label of the answer of the assistant | In this demonstration it reads "Recorded demo answer" | The label says where the answer came from: "Recorded demo answer" for a stored answer and "Muse Spark (live)" for a live one |
| `tutorial.sections[persona_agent_operator].steps[1]` | The heading of the agent screen and what it shows | The page says the run buttons are off, and "More details" is opened | The heading reads "Waiting work" with the number of cases that wait beside it |
| `tutorial.sections[persona_agent_operator].steps[2]` | The batch button and the empty queue | Only the wording of the batch button | The note beside the button reads "Nothing is waiting" when no case waits |
| `tutorial.sections[persona_agent_operator].steps[3]` | What the operator reads after a run | The case leaves the table and "Recent results" is read | "Last run" is read for the run itself, and "Needs attention" with "Try again" for the work that failed |
| `tutorial.sections[persona_agent_operator].steps[5]` | The steward assistant screen of the operator | The assistant is awake and the work of the queue may be prepared | The button reads "Put agent to sleep" and the counts under "More details" read "Recommendations", "High", "Review" and "Held" |
| `tutorial.sections[persona_data_steward].intro` | The role of the steward assistant | The steward assistant only proposes and the steward records the decision | The steward wakes the assistant, decides every recommendation and settles the record |
| `tutorial.sections[persona_data_steward].steps` | The whole section, now ten steps | Five steps: prepare the recommendations, approve a parcel link, confirm an identity link, read the master records | Wake the assistant and put it back to sleep, prepare the recommendations and read the pill and the reason of each, accept or clear each recommendation, accept a batch on "/steward/batch", read "Submitted vs record" and "Open the original submission", close an issue with "Close with a reason", and read the "Data follow-up: parcel not confirmed" tag on the work queue |
| `tutorial.sections[persona_permit_reviewer].steps[0]` | The work queue of the reviewer | You land on the "Work queue" | The issue of a case that waits for the applicant reads "Waiting for the applicant's answer" |
| `tutorial.sections[persona_permit_reviewer].steps[1]` | The sections of the permit workspace | The permit workspace opens for that application | The sections are named, and the "Decision" section starts open when the next action is to decide or to read the decision |
| `tutorial.sections[persona_permit_reviewer].steps[4]` | The result of the checks | The rule results appear and Data follow-up does not refuse the decision | A check that could not run because the parcel is not confirmed is listed as Not checked |
| `tutorial.sections[persona_permit_reviewer].steps[5]` | Approving against a check that failed | The reviewer records an exception reason when required | The field is named: "Exception reason" |
| `tutorial.sections[persona_permit_reviewer].steps[6]` | New step | Not covered | Choosing "Needs information" fills the "Rationale (internal record)" with the request and sends the case back to the applicant |
| `howto.guides[review-an-application-and-record-a-decision].steps` | The whole guide, now ten steps | Nine steps: the queue, the tabs, the parcel, the checks, the blockers, the decision form, the outcome, the rationale, the submit | The chips of today (including "Waiting for the applicant"), the search and its clear, the tags of the row, the sections of the workspace, the tabs, the checks and the Not checked rows, the manual decision beside "Confirm the recommendation" and "Revert the recommendation", the exception reason for an approval against a failed check, and "Needs information" with the prefilled rationale |
| `howto.guides[review-an-application-and-record-a-decision].result` | The last line | Issue permit stays refused until the fee is assessed, paid and reconciled | The label is quoted as "Issue permit" |
| `howto.guides[resolve-a-data-issue].steps` | The whole guide, now ten steps | Eight steps about the Cedarline match alone, three of them written by the overlay of the steward lane | The guide opens with waking the steward assistant, preparing the recommendations and reading the confidence and the reason of each; it then keeps the Cedarline comparison, the rejection of the near-duplicate, the confirmation of the matching record, "Clear recommendation", "Explain with Muse", the batch "Accept all high-confidence" on "/steward/batch", and the manual close "Close with a reason" |
| `howto.guides[resolve-a-data-issue].result` | The last line | A rejected match links nothing, and the source record keeps all its values | A confirmed link ties the source record to the master record and neither record’s values are overwritten; the assistant prepares and the steward decides |

The Data Steward holds the grant `agent.toggle.steward_assist` for its own
assistant, and `agent.run.steward_assist` to ask it for a recommendation, so
the steward may wake and run the assistant on its own screen.

## `repo/config/help_content.d/operator.json`

| Entry | What changed | Before | After |
| --- | --- | --- | --- |
| `howto.guides[run-the-agents].steps[0]` | The home of the operator | The counts and the state of every agent | The "Incoming" panel is named and reads "Nothing is waiting." when no case waits |
| `howto.guides[run-the-agents].steps[1]` | The agent screen | The run buttons and the batch button | The heading reads "Waiting work" with the number of cases beside it, and the note beside the button reads "Nothing is waiting" |
| `howto.guides[run-the-agents].steps[3]` | What the operator reads after a run | The message at the top | "Last run" is read for the run itself, and the "Signals" of a row of the intake queue are named |
| `howto.guides[run-the-agents].steps[6]` | The steward assistant screen | The work of the queue of the Data Steward is prepared | The "Waiting work" count of the assistant is named |

## `repo/config/help_content.d/steward.json`

| Entry | What changed | Before | After |
| --- | --- | --- | --- |
| `howto.guides[resolve-a-data-issue]` | The override of the guide is removed | The lane overrode steps 4, 5 and 7 of the guide | The guide is written once, in `repo/config/help_content.json`, and the lane keeps its own two guides |

## `repo/config/ui_glossary.json`

| Entry | What changed | Before | After |
| --- | --- | --- | --- |
| `terms.steward_assistant` | New term | No term for the assistant of the Data Steward | "Steward assistant": it reads the task, gathers the evidence and proposes a decision with a confidence and a reason; the steward wakes it and decides every proposal |
| `screens.steward` | The help of the Data issues screen | The work queue of record matches and source problems | The steward assistant is named, and waking it and deciding each proposal is listed |
| `screens.review_queue` | The chips of the next action | Six chips | The chip "Waiting for the applicant" is added |

## `repo/tests/integration/test_help_docs_steward.py`

| Entry | What changed | Before | After |
| --- | --- | --- | --- |
| The fixture | The recorded issue of the demonstration | Only the Cedarline proposals were seeded | One recorded data issue is added, so the page that closes an issue by hand is read |
| `LABELS` and `page_of` | The labels the steward help quotes | Twenty-four labels, read on the queue, the sources, the activity and the cases | Nineteen labels are added: the wake and the sleep of the assistant, "Prepare recommendations", the three confidences, the panel of the task, "Reason", "Accept recommendation", "Clear recommendation", "Explain with Muse", "Reject match", "Decision note", the batch button and "Accept these", and the manual close with "Close as" and "Note". The new page cases read the queue and the task with the assistant awake, the batch and the assistant screen of the Agent Operator |

No assertion was weakened or removed: every label the steward help quotes is
now checked against the element of the page that shows it.

## Left alone on purpose

- The tutorial keeps its five sections, one for each persona the selector
  offers today. `repo/config/actors.json` and the selector list five
  selectable personas, and the shared test of the tutorial expects the five
  sections in that order, so the Agent Operator stays in the help.
- The architecture note still says that the sandboxed page reads as a static
  page. The sandbox of the iframe carries no allow token, so scripts do not
  run there, and the shared test of that page asserts it.
- The daily allowance of live Muse calls is left as it is. The deployment
  configuration of the hosted demonstration sets
  `ACME_MUSE_LIVE_CALL_CAP` and `ACME_MUSE_DAILY_CALL_CAP` to 100, so the
  number is the one the deployment uses.
