# ACME City Permits: judge walkthrough

Nine steps, about ten minutes. Every record in the app is fictional, and the app issues no real permit.

Start at https://acme-city-permits.onrender.com/walkthrough. The same steps are on that page, and the button on each step switches to the right persona and opens the screen. To run the app on a local computer instead, follow `repo/USER_TEST_GUIDE.md` and open http://127.0.0.1:8266/walkthrough.

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

- Do: Choose a deck or fence permit. Type a street and pick a suggested address. Answer the questions, submit, then open Track.
- Look for: A reference number and the tracker. The help panel cites the published ACME rule behind each answer.

## 4. Let the agent route the work

As **Agent Operator**, open `/agent/intake`.

- Do: Press Wake agent if the intake agent is asleep, then press Process all waiting.
- Look for: Each waiting case goes to early resolution or to review, with its reason beside it.

## 5. Clear a case for review

As **Data Steward**, open `/queue/early-resolution`.

- Do: Open the case from step 3 if it is listed, or the top case. Read each finding and the evidence behind it.
- Look for: Advance to review is refused while a blocking finding stands. Return to the applicant is the other way out.

## 6. Decide a case

As **Permit Reviewer**, open `/queue/review`.

- Do: Open the case from step 3, or the top case. Press Run application checks, read the agent's recommendation, then Record review decision with a reason.
- Look for: Deciding and issuing are separate. Issue permit stays blocked until the fee is assessed, paid and reconciled, so a blocked button is expected.

## 7. Check the record of the decision

As **City Administrator**, open `/ops/audit`.

- Do: Find the decision recorded in step 6.
- Look for: Who acted, when, on which case, and the reason they gave.

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

This file mirrors `repo/src/acme_city/ui/guide_views.py` (`WALKTHROUGH`); `repo/tests/unit/test_judge_walkthrough_doc.py` fails if they differ.
