# MCP server for ACME City Permits: plan (future, not to be built now)

This document is a plan. Nothing of it is built. The demonstration has no MCP
server, no MCP tools and no MCP token today. The stories that come from this
plan are in `docs/operations/USER_STORIES.md`, under "Future feature:
assistants through MCP".

Planned 2026-11-01 by a Claude planning subagent from the code at main fd41e14. Unverified: whether any write path already carries an idempotency key (only finance has one), and the exact permission names per persona.

## 1. Purpose and top use cases

Let an AI assistant work the permit system as one of the five personas, with that persona's limits. People still decide.

1. Resident's assistant (Applicant): looks up the fence rules and fees, checks the resident's facts, explains gaps, then submits the resident's own application after the resident confirms.
2. Reviewer's assistant (Permit Reviewer): summarizes a case, lists the rule results and open items, prepares a draft recommendation. It never decides or issues.
3. Administrator's assistant (City Administrator): runs a what-if on a rule or fee change, reads the impact preview, explains the audit trail.

Data Steward and Agent Operator get read tools in phase 1; their actions wait for phase 3.

## 2. Shape

- Transport: stdio for local use; streamable HTTP for the hosted demo.
- Location: `repo/src/acme_city/mcp_server/` (`server.py`, `identity.py`, `tools_<persona>.py`, `resources.py`, `prompts.py`), entry point `acme-mcp` in `repo/pyproject.toml`; HTTP form mounted under `/mcp` in `app.py`.
- Calls the service layer in-process (e.g. `permit_service(session)` in `permits/router.py`, `catalog_service` in `rules/router.py`, `change_service` in `changes/router.py`, `muse_service` in `muse/router.py`), reusing the command schemas (e.g. `SubmitApplicationCommand` in `permits/schemas.py`). `/api/*` is the fallback for a remote-only deployment. No tool reads HTML.

## 3. Identity and permissions

- The server resolves the actor; no tool takes a role or persona argument. Each MCP session is bound to one persona when issued.
- Local: launcher passes `--persona persona_applicant`. Hosted: a person picks a persona (`/api/session/select`), the demo shows a short-lived MCP token tied to that session; stored hashed, expires with the session, revoked on `DELETE /api/session`; never in output or logs.
- Read-only by default (`read` scope); `write` scope must be requested; staff write scope off unless enabled by setting.
- Writes are two-step: preview plus one-time confirmation id, then `confirm_action(id)`; the id expires in minutes and works once.
- Audit: every call, allowed or denied, through `AuditService.append` (`audit/service.py`) with metadata `{channel: "mcp"}`; a new actor type "Assistant via MCP" next to person, agent and system (`ops/audit_log.py`) and a filter on the audit page.

## 4. Tools (R read, W write with confirmation)

- Shared: `whoami` (R, `GET /api/session`), `list_permit_types` (R, rules catalog).
- Applicant: `get_rules` (R, `resolve_rule_set`), `check_application` (R, `/apply/<type>/check` and `applicant_help/service.py`), `list_my_applications` / `get_my_application` (R), `submit_application` (W), `revise_application` (W).
- Agent Operator: `get_agent_status` (R, `agents/summary.py`), `list_muse_runs` (R, `GET /api/muse/runs`), `request_agent_run` (W, phase 3).
- Data Steward: `list_source_links`, `get_trusted_view` (R, `registry/router.py`), `list_datasets`, `get_domain_responsibility` (R, `governance/router.py`), `propose_source_link` (W, phase 3; proposes, never decides).
- Permit Reviewer: `list_review_queue`, `get_case`, `get_evaluations` (R), `summarize_case` (R, Muse-gated), `get_recommendation` (R), `prepare_recommendation` (W, phase 3; draft only).
- City Administrator: `list_rule_versions`, `get_rule_version` (R), `run_what_if` (R, `policy/service.py`), `preview_change_impact` (R, `POST /api/changes/impact/preview`), `search_audit` (R).
- Never exposed: decide, issue, approve, publish, reconfirm, finance allocation confirm, payment import.
- Resources: `acme://rules/{permit_type}`, `acme://permit-types`, `acme://case/{id}/summary`, `acme://help/{slug}`, `acme://personas`.
- Prompts: `fence_permit_helper`, `review_case_brief`.

## 5. Safety

- Same `RateLimitMiddleware` (`core/protection.py`); `/mcp` added to `classify`; stdio uses the same token bucket per session.
- Muse calls go through `muse/service.py` with every cap and switch; a cap hit returns "limit reached" and the deterministic result still works.
- Output built from response models only; no tokens, cookies, keys, session ids or CSRF values.
- Refuses to start against a database not marked as demo data.
- Every write takes a `command_key`; a repeat returns the first result (small key table, finance `idempotency_key` as the pattern).
- People decide: no tool decides, approves, issues or publishes.
- MCP tokens replace CSRF; the endpoint ignores browser cookies.

## 6. Phases and acceptance

1. Read-only tools, resources, prompts. Tests: per-persona tool lists; cross-persona call denied and audited; no secrets in output; rate limit message; stdio and HTTP agree. Acceptance: fence rule and fee check end to end; case summary cites sources.
2. Resident submit. Tests: needs `write` scope; preview writes nothing; repeated `command_key` makes one application; cannot submit for another party; audit shows "Assistant via MCP". Acceptance: from "can I build a fence" to a submitted application after the resident confirms.
3. Staff actions with confirmation. Tests: drafts cannot be confirmed via MCP; confirmation id single-use and expiring; Muse cap degrades cleanly; no decide/issue/approve/publish tool registered; Administrator cannot run agents. Acceptance: the reviewer's draft shows "prepared by assistant" and a person confirms.

## 7. Open questions

1. Who may enable write scope on the hosted demo; default off?
2. New audit actor type, or a channel flag on "person"?
3. In-process services or `/api/*` for HTTP?
4. Token lifetime; several tokens per persona?
5. `summarize_case`: Muse or deterministic when the live gate is closed?
6. Which Operator controls in `agents/control.py` are safe in phase 3?
7. A lower per-client write cap for MCP on the hosted demo?
