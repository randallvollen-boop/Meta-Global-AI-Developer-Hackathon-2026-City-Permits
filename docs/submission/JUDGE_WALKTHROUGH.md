# ACME City Permits: judge walkthrough

Nine steps, about ten minutes. Every record in the app is fictional, and the app issues no real permit.

Start at https://acme-city-permits.onrender.com/walkthrough. The same steps are on that page, and the button on each step switches to the right persona and opens the screen. To run the app on a local computer instead, follow `repo/USER_TEST_GUIDE.md`. From `repo/`, run `uv run python scripts/prepare_user_test.py --mode demo-synthetic` and then `uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266`, and open http://127.0.0.1:8266/walkthrough. The demo-synthetic mode loads the synthetic year of permits that steps 8 and 9 need.

The permit life cycle behind these steps is at `/lifecycle`: every status, every move, and who makes each move.

## 1. Watch the tour (optional)

Open `/select`.

- Do: Play the video above the persona cards. It runs under three minutes.
- Look for: Five personas, each a fictional person with one job. Every record in the app is fictional.

## 2. Read the permit life cycle

Open `/lifecycle`.

- Do: Read the main path across the top, then the statuses a case can move to instead.
- Look for: Each move names who makes it. An agent only routes cases. A person decides and issues.

## 3. Apply for a permit

As **Applicant**, open `/apply`.

- Do: Choose Residential deck or fence. Keep the applicant name already filled in. Type 400 Lantern Row and pick the suggested address. Answer the questions, for example a 6 ft fence in the side or rear yard, 2 ft from the property line. Attach a small .txt file for each of the two required documents, tick the certification, press Submit application, then press Track application. Submit once: a second application for the same project at the same address is flagged as a duplicate. To see early resolution later, submit a second application at another address, such as 100 Kestrel Way, and tick Sent to the City separately for one document instead of attaching it.
- Look for: A reference number such as SYN-APP-614, and a tracker that lists both documents as received. The help panel cites the published ACME rule behind each answer.

## 4. Let the agent route the work

As **Agent Operator**, open `/agent/intake`.

- Do: Press Wake agent. The page shows it awake straight away. Then press Process next 20, or Process one beside your case. Open All runs, and press View run on the row for your case. Then open Steward assistant (/agent/steward_assist) and press Wake agent there too, so the Data Steward can ask it for recommendations.
- Look for: The run shows Completed, and its Router line under Processing steps says Ready for review in the Building area. A case with a blocking finding, such as a missing document, goes to early resolution instead, and the Router line gives that reason.

## 5. Clear a case for review

As **Data Steward**, open `/steward`.

- Do: In Data issues, press Prepare recommendations. The steward assistant gives each task it works on (up to 20 per press) a High, Review or Held pill and a one-line reason. Open the Check the property issue that names your case reference. Press Start under Approve parcel link for that reference, write a decision note and submit it. Then open the Check the person identity issue from the ACME ePermit Portal source, press Start under Confirm link to Tamsin Aldous, write a decision note and submit it.
- Look for: The assistant only proposes: Accept recommendation and Accept all high-confidence (N), which shows the exact list first, record the decision in your name. Without these two approvals the Permit Reviewer cannot approve the case: the decision is refused with the blockers parcel_link_unapproved and identity_link_unapproved. A case that arrives with a blocking finding, such as a second application with a missing document, waits in Early resolution instead (/queue/early-resolution). There Advance to review is off until the finding is cleared, and Return to the applicant is the other way out.

## 6. Decide a case

As **Permit Reviewer**, open `/queue/review`.

- Do: Open the case from step 3. On the People & property tab, press Start under Confirm parcel and submit it. The page updates in place and keeps your tab. On the Review tab, press Start under Run application checks and submit it: the rule results appear and the decision form is offered. Press Start under Record review decision, choose Approve, write a rationale and submit it. Then try Issue permit.
- Look for: Deciding and issuing are separate. After the approval, Issue permit is refused (the permit may not be issued yet) until the fee is assessed, paid and reconciled on the Reconciliation screen, so a refusal is expected.

## 7. Check the record of the decision

As **City Administrator**, open `/ops/audit`.

- Do: Choose Recorded permit decision in the Action filter and press Apply filters, then press View details on the top row.
- Look for: The actor, the time, the decision record and, under References, the case the decision belongs to, named by its reference (SYN-APP-nnn, the number from step 3). A denial also shows its reason code under Recorded detail. The written rationale is on the case page, not in the audit log.

## 8. See the city at a glance

As **City Administrator**, open `/insight/city`.

- Do: Filter the City view by permit type or outcome. Then open the planning overview and try a what if policy scenario.
- Look for: The map, the counts and the definition printed beside each figure.

## 9. Look up permits as a resident

Open `/city/community`.

- Do: Search by a street name on the City of Acme website.
- Look for: The public record shows the permit, the parcel and the outcome. It never shows a homeowner's name, documents or fees.

## Future features

- A withdraw action for applicants. The Withdrawn status exists, but no action in the app sets it yet.
- Application checks that leave a decided case decided. Today, running them on an approved or denied case moves it back to Ready for review.
- Issued permits that stay closed. Today a record correction can reopen one.
- Automatic linking on the hosted demo. It is built (Steward automation at `/steward/automation`, and the prepare mode `steward-automation`), but the hosted demo runs it paused.

This file mirrors `repo/src/acme_city/ui/guide_views.py` (`WALKTHROUGH`); `repo/tests/unit/test_judge_walkthrough_doc.py` fails if they differ.
