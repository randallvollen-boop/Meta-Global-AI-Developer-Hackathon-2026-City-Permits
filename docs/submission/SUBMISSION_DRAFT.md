# ACME City Permits

## Draft status

This is submission text for Randall to review and submit himself. The current hosted build has four complete operational personas. The redesign branch has added Agent Operator as a fifth selectable persona with its grants, navigation, and a temporary home on the intake agent screen. Its full operations workspace is still in progress and is not yet on the hosted demo. Update the Agent Operator paragraph and the try it section after that work is integrated.

## Summary

ACME City Permits is a fictional municipal permitting application that follows a permit from intake through identity and property review, application checks, a human decision, fee reconciliation, and permit issuance. It combines registry master data, versioned rules, role based actions, audit history, and bounded Meta Muse proposals while keeping every authoritative decision with a person or deterministic service.

## What it does

### Applicant

An applicant can choose from seventeen fictional permit types, locate a property, save a draft, submit an application, replace documents, answer a request for information, track progress, read messages from the City, and download a submission or issued permit. The help panel uses published ACME rules and the applicant's own case. It cites its sources and says when it cannot answer.

### Data steward

A data steward works the intake and early resolution queues, runs the intake agent when it is awake, reviews possible duplicate records, approves identity and parcel links, and accepts or corrects values proposed from documents. The steward can also inspect master records, source records, provenance, and change activity. These actions do not approve a permit.

### Permit reviewer

A permit reviewer works the review queue, checks the property and application facts, runs the adjudication agent when it is awake, and reads its rule based recommendation. The reviewer can confirm or revert that recommendation, record the decision of record, add conditions, request revisions, and issue a permit only after the required links, decision, fee assessment, payment allocation, and reconciliation are complete.

### City administrator

A city administrator sees the planning overview, operations measures, audit history, support requests, source governance, rules, fee schedules, users, access, appearance, and reconciliation. The administrator can simulate incoming applications, wake or stop the agents, manage fictional configuration, run invariant checks, and create governed policy drafts. Configuration authority does not grant permit decision authority.

### Agent operator

The redesign branch now includes Agent Operator as the fifth selectable persona. The built Wave 0 slice gives this persona the agent operations permission bundle, agent navigation, the demo switch entry, and a temporary home on the intake agent screen. The full Agent Operator workspace, run history, processing controls, and case views remain in progress and must not be described as hosted until they are integrated.

## How it uses Meta Muse

Meta Muse Spark can propose structured values from received document text and can produce bounded record match proposals. The application validates the response against a strict schema and records its source, usage, latency, and validation result. A data steward decides whether a proposed value or link becomes part of the governed record.

The applicant help and City policy paths also have bounded Muse support. Muse can draft a cited answer, explain a policy simulation, write a briefing from typed facts, or propose a policy change. The server checks sources, claims, figures, rule citations, and allowed change types. A failed answer is refused. A policy proposal is not saved until an authorized person chooses to save it, and it still follows the normal draft and approval process.

Muse Image support can generate fictional permit type icons through a governed administrator action with daily limits and recorded provenance. The hosted demo keeps live Muse calls off. It uses clearly labelled replay fixtures so visitors can follow the experience without sending a provider request.

## Architecture

* A Python FastAPI service renders the public site, applicant portal, and staff interface with Jinja templates and small vanilla JavaScript enhancements.

* SQLAlchemy and Alembic manage one SQLite database that stores applications, master records, source links, decisions, rules, fees, audit records, model runs, and workflow state.

* Three simulated source adapters represent permitting, geographic information, and finance systems. A database outbox records governed changes and acknowledgments.

* Server held actors, scoped permissions, record scope, version checks, audit history, and explicit human actions protect every sensitive read and write.

* The Meta Muse adapter allows only named models and strict schemas, bounds each request, never retries automatically, labels live and replay results, and cannot approve, price, or issue a permit.

## How to try it

1. Open https://acme-city-permits.onrender.com.

2. Use the demo switcher to choose a persona available in the hosted build.

3. As Applicant, start a fictional deck or fence application, save it, submit it, and open its tracker.

4. As Data Steward, inspect the intake queue and the evidence behind proposed record and parcel links.

5. As Permit Reviewer, open a case in review, inspect the checks and recommendation, then follow the separate decision and issuance steps.

6. As City Administrator, open the planning overview, operations, governance, rules, reconciliation, support, and audit screens. The hosted demo uses replay for Muse paths and does not make live Muse calls.

7. After the redesign is integrated, confirm that Agent Operator appears in the demo switcher and replace the draft limitation above with the verified hosted workflow.

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.
